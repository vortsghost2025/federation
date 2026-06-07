class PatternDistributor {
  constructor({ clusterId }) {
    this.clusterId = clusterId;
    this.patterns = new Map();
    this.receivedPatterns = new Map();
    this.shares = new Map();
  }

  registerPattern(id, pattern, classification) {
    this.patterns.set(id, { pattern, classification });
    return true;
  }

  distributePattern(id, targetClusters) {
    if (!this.patterns.has(id)) return { success: false, distributed: 0 };
    this.shares.set(id, (this.shares.get(id) || 0) + 1);
    return { success: true, distributed: targetClusters.length };
  }

  receivePattern(id, pattern, fromCluster) {
    if (!this.receivedPatterns.has(fromCluster)) {
      this.receivedPatterns.set(fromCluster, []);
    }
    this.receivedPatterns.get(fromCluster).push({ id, pattern });
  }

  getReceivedPatterns(fromCluster) {
    return this.receivedPatterns.get(fromCluster) || [];
  }

  getPatternStats() {
    let totalShares = 0;
    for (const count of this.shares.values()) {
      totalShares += count;
    }
    return {
      totalPatterns: this.patterns.size,
      totalShares
    };
  }
}

class AnomalyAggregator {
  constructor({ clusterId }) {
    this.clusterId = clusterId;
    this.localAnomalies = new Map();
  }

  reportAnomaly(id, anomaly) {
    this.localAnomalies.set(id, { ...anomaly });
    return true;
  }

  aggregateAnomalies(clusterAnomalies) {
    const aggregated = {};
    const severityOrder = { CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0 };

    for (const [clusterId, anomalies] of Object.entries(clusterAnomalies)) {
      for (const entry of anomalies) {
        const type = entry.anomaly.type;
        if (!aggregated[type]) {
          aggregated[type] = {
            count: 0,
            avgAffected: 0,
            totalAffected: 0,
            highestSeverity: 'LOW',
            clusters: []
          };
        }
        aggregated[type].count++;
        aggregated[type].totalAffected += entry.affectedNodes;
        aggregated[type].clusters.push(clusterId);

        const currentMax = severityOrder[aggregated[type].highestSeverity] || 0;
        const newSeverity = severityOrder[entry.severity] || 0;
        if (newSeverity > currentMax) {
          aggregated[type].highestSeverity = entry.severity;
        }
      }
    }

    for (const type of Object.keys(aggregated)) {
      aggregated[type].avgAffected = aggregated[type].totalAffected / aggregated[type].count;
      aggregated[type].clusters = [...new Set(aggregated[type].clusters)];
    }

    return { success: true, aggregated };
  }

  getAnomalyReport() {
    const types = new Set();
    for (const [id, anomaly] of this.localAnomalies) {
      types.add(anomaly.type);
    }
    return {
      totalTypes: types.size,
      totalAnomalies: this.localAnomalies.size
    };
  }
}

class StrategyConsensus {
  constructor({ clusterId, consensusThreshold = 0.5 }) {
    this.clusterId = clusterId;
    this.consensusThreshold = consensusThreshold;
    this.strategies = new Map();
  }

  proposeStrategy(id, strategy, proposerClusterId) {
    if (this.strategies.has(id)) return { success: false };
    this.strategies.set(id, {
      strategy,
      proposerClusterId,
      votes: new Map(),
      status: 'PENDING'
    });
    return { success: true };
  }

  vote(strategyId, clusterId, vote, reason) {
    const strategy = this.strategies.get(strategyId);
    if (!strategy) return false;
    strategy.votes.set(clusterId, { vote, reason });
    return true;
  }

  tallyVotes(strategyId) {
    const strategy = this.strategies.get(strategyId);
    if (!strategy) return { status: 'REJECTED' };

    let yesCount = 0;
    let noCount = 0;
    for (const [clusterId, voteEntry] of strategy.votes) {
      if (voteEntry.vote === 'YES') yesCount++;
      else if (voteEntry.vote === 'NO') noCount++;
    }
    const totalVotes = yesCount + noCount;
    const support = totalVotes > 0 ? yesCount / totalVotes : 0;

    strategy.status = support >= this.consensusThreshold ? 'APPROVED' : 'REJECTED';
    return { status: strategy.status, yesCount, noCount, support };
  }

  getConsensusStrategies() {
    return Array.from(this.strategies.entries()).map(([id, data]) => ({
      id,
      ...data,
      votes: Object.fromEntries(data.votes)
    }));
  }
}

class KnowledgeReplicator {
  constructor({ clusterId, replicationFactor = 3 }) {
    this.clusterId = clusterId;
    this.replicationFactor = replicationFactor;
    this.localKnowledge = new Map();
    this.remoteKnowledge = new Map();
    this.verificationStatus = new Map();
  }

  storeKnowledge(id, data, classification) {
    this.localKnowledge.set(id, { data, classification, storedAt: Date.now() });
    this.verificationStatus.set(id, new Set());
    return { success: true };
  }

  replicateKnowledge(id, targetClusters) {
    if (!this.localKnowledge.has(id)) return { success: false, replicatedTo: [] };
    const toReplicate = targetClusters.slice(0, this.replicationFactor);
    for (const clusterId of toReplicate) {
      this.remoteKnowledge.set(`${clusterId}:${id}`, { id, data: this.localKnowledge.get(id).data, source: this.clusterId });
    }
    return { success: true, replicatedTo: toReplicate };
  }

  receiveReplicatedKnowledge(id, data, fromCluster) {
    this.remoteKnowledge.set(fromCluster, { id, data, source: fromCluster });
  }

  verifyKnowledge(id, fromCluster) {
    if (!this.remoteKnowledge.has(fromCluster)) return { success: false };
    const verifications = this.verificationStatus.get(id);
    if (verifications) verifications.add(fromCluster);
    return { success: true };
  }

  getReplicationStats() {
    let criticalItems = 0;
    for (const [id, item] of this.localKnowledge) {
      if (item.classification === 'CRITICAL') criticalItems++;
    }
    return {
      totalKnowledge: this.localKnowledge.size,
      criticalItems
    };
  }
}

class FederatedKnowledgeExchangeEngine {
  constructor({ clusterId }) {
    this.clusterId = clusterId;
    this.patternDistributor = new PatternDistributor({ clusterId });
    this.anomalyAggregator = new AnomalyAggregator({ clusterId });
    this.strategyConsensus = new StrategyConsensus({ clusterId });
    this.knowledgeReplicator = new KnowledgeReplicator({ clusterId });
    this.exchangeLog = [];
  }

  exchangePatternKnowledge(id, pattern, targetClusters) {
    this.patternDistributor.registerPattern(id, pattern, 'STANDARD');
    const result = this.patternDistributor.distributePattern(id, targetClusters);
    this.exchangeLog.push({ type: 'PATTERN', id, timestamp: Date.now() });
    return result;
  }

  synthesizeAnomalies(clusterAnomalies) {
    const result = this.anomalyAggregator.aggregateAnomalies(clusterAnomalies);
    const types = Object.keys(result.aggregated);
    for (const type of types) {
      this.anomalyAggregator.reportAnomaly(`synth-${type}`, { type, severity: result.aggregated[type].highestSeverity, affectedNodes: 0 });
    }
    return { totalTypes: types.length, types, aggregated: result.aggregated };
  }

  proposeAndConsensus(id, strategy, proposerClusterId, clusterIds) {
    const proposed = this.strategyConsensus.proposeStrategy(id, strategy, proposerClusterId);
    if (!proposed.success) return { status: 'REJECTED' };
    for (const clusterId of clusterIds) {
      this.strategyConsensus.vote(id, clusterId, 'YES', 'Approved by engine');
    }
    return this.strategyConsensus.tallyVotes(id);
  }

  storeAndReplicateCritical(id, data, targetClusters) {
    const stored = this.knowledgeReplicator.storeKnowledge(id, data, 'CRITICAL');
    if (!stored.success) return { success: false };
    const replicated = this.knowledgeReplicator.replicateKnowledge(id, targetClusters);
    this.exchangeLog.push({ type: 'CRITICAL_KNOWLEDGE', id, timestamp: Date.now() });
    return { ...replicated, success: true };
  }

  getExchangeStatus() {
    return {
      patterns: this.patternDistributor.patterns.size,
      anomalies: this.anomalyAggregator.localAnomalies.size,
      knowledge: this.knowledgeReplicator.localKnowledge.size,
      logEntries: this.exchangeLog.length
    };
  }
}

export {
  PatternDistributor,
  AnomalyAggregator,
  StrategyConsensus,
  KnowledgeReplicator,
  FederatedKnowledgeExchangeEngine
};
