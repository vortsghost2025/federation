#!/usr/bin/env node
/**
 * Gastown NPC Monitor Listener
 * Listens to Redis Pub/Sub channel 'federation:npc_monitor' and broadcasts to WebSocket clients
 */

const WebSocket = require('ws');
const redis = require('redis');

// Configuration
const REDIS_URL = process.env.REDIS_URL || 'redis://redis:6379/0';
const MONITOR_CHANNEL = 'federation:npc_monitor';
const WS_PORT = process.env.WS_PORT || 8080;
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';

// Simple logger
const logger = {
  info: (msg) => console.log(`[INFO] ${new Date().toISOString()} - ${msg}`),
  warn: (msg) => console.log(`[WARN] ${new Date().toISOString()} - ${msg}`),
  error: (msg) => console.log(`[ERROR] ${new Date().toISOString()} - ${msg}`),
  debug: (msg) => {
    if (LOG_LEVEL === 'debug') {
      console.log(`[DEBUG] ${new Date().toISOString()} - ${msg}`);
    }
  }
};

class GastownListener {
  constructor() {
    this.wss = null;
    this.redisClient = null;
    this.subscriber = null;
    this.clients = new Set();
  }

  async init() {
    try {
      // Initialize WebSocket server
      this.wss = new WebSocket.Server({ port: WS_PORT });
      this.wss.on('connection', (ws) => {
        logger.info(`New WebSocket client connected. Total clients: ${this.clients.size + 1}`);
        this.clients.add(ws);

        ws.on('close', () => {
          logger.info(`WebSocket client disconnected. Total clients: ${this.clients.size}`);
          this.clients.delete(ws);
        });

        ws.on('error', (error) => {
          logger.error(`WebSocket error: ${error.message}`);
        });
      });

      logger.info(`WebSocket server listening on port ${WS_PORT}`);

      // Initialize Redis client
      this.redisClient = redis.createClient({ url: REDIS_URL });
      this.redisClient.on('error', (err) => {
        logger.error(`Redis client error: ${err}`);
      });
      await this.redisClient.connect();
      logger.info('Connected to Redis');

      // Create subscriber (separate connection for pub/sub)
      this.subscriber = this.redisClient.duplicate();
      await this.subscriber.connect();
      logger.info('Redis subscriber connected');

      // Subscribe to the monitor channel
      await this.subscriber.subscribe(MONITOR_CHANNEL, (message) => {
        logger.debug(`Received message on ${MONITOR_CHANNEL}: ${message}`);
        this.broadcastToClients(message);
      });

      logger.info(`Subscribed to Redis channel: ${MONITOR_CHANNEL}`);

    } catch (error) {
      logger.error(`Failed to initialize Gastown listener: ${error}`);
      throw error;
    }
  }

  broadcastToClients(message) {
    if (this.clients.size === 0) {
      logger.debug('No WebSocket clients connected, skipping broadcast');
      return;
    }

    const data = Buffer.isBuffer(message) ? message.toString('utf8') : message;
    const packet = JSON.stringify({
      timestamp: Date.now(),
      data: data
    });

    let failed = 0;
    this.clients.forEach((client) => {
      if (client.readyState === WebSocket.OPEN) {
        try {
          client.send(packet);
        } catch (error) {
          logger.error(`Failed to send message to client: ${error.message}`);
          failed++;
        }
      } else {
        failed++;
      }
    });

    if (failed > 0) {
      logger.warn(`Failed to broadcast to ${failed} clients`);
    } else {
      logger.debug(`Broadcasted message to ${this.clients.size} clients`);
    }
  }

  async shutdown() {
    logger.info('Shutting down Gastown listener...');
    if this.wss) {
      this.wss.close();
    }
    if (this.subscriber) {
      await this.subscriber.quit();
    }
    if (this.redisClient) {
      await this.redisClient.quit();
    }
    logger.info('Gastown listener shutdown complete');
  }
}

// Start the listener
const listener = new GastownListener();
listener.init().catch((error) => {
  logger.error(`Fatal error: ${error}`);
  process.exit(1);
});

// Handle graceful shutdown
process.on('SIGINT', async () => {
  logger.info('Received SIGINT, shutting down...');
  await listener.shutdown();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  logger.info('Received SIGTERM, shutting down...');
  await listener.shutdown();
  process.exit(0);
});