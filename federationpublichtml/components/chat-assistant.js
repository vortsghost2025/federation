// Chat Assistant Component for Federation Simulation
// Vanilla JS, no dependencies

const ChatAssistant = {
  // Configuration
  config: {
    container: null,
    apiEndpoint: '/api/chat/query',
    stateEndpoint: '/api/federation/state',
    pollInterval: 5000, // ms to poll for state updates
    zIndex: 1000
  },

  // State
  state: {
    isChatOpen: false,
    federationState: {
      morale: 0.7,
      identity: 0.8,
      anxiety: 0.2,
      confidence: 0.9,
      expansion_hunger: 0.5,
      diplomacy_tendency: 0.6
    },
    messages: [] // Array of {text: string, isUser: boolean}
  },

  // DOM elements
  elements: {
    container: null,
    toggleButton: null,
    chatWindow: null,
    chatHeader: null,
    chatMessages: null,
    chatInput: null,
    chatSendButton: null
  },

  // Initialize the chat assistant
  init: function(options = {}) {
    // Merge options with default config
    if (options.container) this.config.container = options.container;
    if (options.apiEndpoint) this.config.apiEndpoint = options.apiEndpoint;
    if (options.stateEndpoint) this.config.stateEndpoint = options.stateEndpoint;
    if (options.pollInterval) this.config.pollInterval = options.pollInterval;

    // Create the chat UI
    this.createUI();

    // Start polling for state updates
    this.startStatePolling();

    // Return the instance for chaining
    return this;
  },

  // Create the chat UI elements
  createUI: function() {
    // Get or create container
    if (typeof this.config.container === 'string') {
      this.elements.container = document.querySelector(this.config.container);
    } else if (this.config.container instanceof HTMLElement) {
      this.elements.container = this.config.container;
    }

    if (!this.elements.container) {
      console.error('Chat Assistant: Container not found');
      return;
    }

    // Create toggle button (fixed position)
    this.elements.toggleButton = document.createElement('button');
    this.elements.toggleButton.id = 'chat-toggle-button';
    this.elements.toggleButton.innerHTML = '💬'; // Chat icon
    this.elements.toggleButton.classList.add('chat-toggle-button');
    this.elements.toggleButton.addEventListener('click', () => this.toggleChat());

    // Create chat window
    this.elements.chatWindow = document.createElement('div');
    this.elements.chatWindow.id = 'chat-window';
    this.elements.chatWindow.classList.add('chat-window');
    this.elements.chatWindow.innerHTML = `
      <div class="chat-header">
        <div class="chat-title">Federation Tactician</div>
        <div class="chat-close-button" id="chat-close-button">✕</div>
      </div>
      <div class="chat-messages" id="chat-messages"></div>
      <div class="chat-input-container">
        <input type="text" id="chat-input" placeholder="Ask about the Federation...">
        <button id="chat-send-button">Send</button>
      </div>
    `;

    // Add elements to container
    this.elements.container.appendChild(this.elements.toggleButton);
    this.elements.container.appendChild(this.elements.chatWindow);

    // Cache elements
    this.elements.chatHeader = this.elements.chatWindow.querySelector('.chat-header');
    this.elements.chatMessages = this.elements.chatWindow.querySelector('#chat-messages');
    this.elements.chatInput = this.elements.chatWindow.querySelector('#chat-input');
    this.elements.chatSendButton = this.elements.chatWindow.querySelector('#chat-send-button');
    const chatCloseButton = this.elements.chatWindow.querySelector('#chat-close-button');

    // Add event listeners
    this.elements.chatSendButton.addEventListener('click', () => this.sendMessage());
    this.elements.chatInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') this.sendMessage();
    });
    chatCloseButton.addEventListener('click', () => this.toggleChat());

    // Apply initial styles
    this.applyStyles();
    this.updateVisualEffects();
  },

  // Toggle chat window visibility
  toggleChat: function() {
    this.state.isChatOpen = !this.state.isChatOpen;
    this.elements.chatWindow.classList.toggle('open', this.state.isChatOpen);
    // Focus input when opening
    if (this.state.isChatOpen) {
      this.elements.chatInput.focus();
    }
  },

  // Send a message to the API
  sendMessage: function() {
    const text = this.elements.chatInput.value.trim();
    if (!text) return;

    // Add user message to chat
    this.addMessage(text, true);
    this.elements.chatInput.value = '';

    // Show loading indicator (optional)
    this.addMessage('...', false); // Placeholder for thinking

    // Send to API
    fetch(this.config.apiEndpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ question: text })
    })
    .then(response => {
      if (!response.ok) throw new Error(`API error: ${response.status}`);
      return response.json();
    })
    .then(data => {
      // Remove the placeholder
      this.removeMessage(this.elements.chatMessages.lastChild);
      // Add the AI response
      const aiResponse = data.response || data.answer || 'No response received';
      this.addMessage(aiResponse, false);
    })
    .catch(error => {
      // Silently handle error - show user-friendly message in chat
      this.removeMessage(this.elements.chatMessages.lastChild);
      this.addMessage('Error: Unable to connect to Federation Tactician.', false);
    });
  },

  // Add a message to the chat display
  addMessage: function(text, isUser) {
    const messageDiv = document.createElement('div');
    messageDiv.classList.add('chat-message');
    messageDiv.classList.add(isUser ? 'user-message' : 'ai-message');
    messageDiv.textContent = text;

    this.elements.chatMessages.appendChild(messageDiv);
    // Scroll to bottom
    this.elements.chatMessages.scrollTop = this.elements.chatMessages.scrollHeight;

    return messageDiv;
  },

  // Remove a message from the chat display
  removeMessage: function(messageElement) {
    if (messageElement && messageElement.parentNode) {
      messageElement.parentNode.removeChild(messageElement);
    }
  },

  // Start polling for federation state updates
  startStatePolling: function() {
    this.fetchState(); // Initial fetch
    setInterval(() => this.fetchState(), this.config.pollInterval);
  },

  // Fetch the current federation state for visual effects
  fetchState: function() {
    fetch(this.config.stateEndpoint)
      .then(response => {
        if (!response.ok) throw new Error(`State API error: ${response.status}`);
        return response.json();
      })
      .then(data => {
        if (data && data.consciousness) {
          this.state.federationState = data.consciousness;
          this.updateVisualEffects();
        }
      })
      .catch(() => {
        // Silently ignore errors to avoid spamming console
      });
  },

  // Update visual effects based on federation state
  updateVisualEffects: function() {
    const state = this.state.federationState;
    const button = this.elements.toggleButton;

    // Reset effects
    button.classList.remove('morale-pulse', 'anxiety-interference');

    // Apply morale pulsing (if morale > 0.7)
    if (state.morale > 0.7) {
      button.classList.add('morale-pulse');
    }

    // Apply anxiety interference (if anxiety > 0.5)
    if (state.anxiety > 0.5) {
      button.classList.add('anxiety-interference');
    }
  },

  // Apply CSS styles for the chat component
  applyStyles: function() {
    // Remove any existing styles for chat assistant to avoid duplication
    const existingStyles = document.getElementById('chat-assistant-styles');
    if (existingStyles) existingStyles.remove();

    const style = document.createElement('style');
    style.id = 'chat-assistant-styles';
    style.textContent = `
      /* Chat Assistant Styles */
      .chat-toggle-button {
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        border: 2px solid #3a3a4c;
        background: transparent;
        color: #e0e0e0;
        font-size: 24px;
        cursor: pointer;
        z-index: 1000;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.3s ease;
        font-family: 'Courier New', monospace;
      }

      .chat-toggle-button:hover {
        border-color: #6a6a7c;
        color: #ffffff;
        background: rgba(255, 255, 255, 0.05);
      }

      .chat-toggle-button.morale-pulse {
        animation: moralePulse 2s ease-in-out infinite;
      }

      .chat-toggle-button.anxiety-interference {
        position: relative;
        overflow: hidden;
      }

      .chat-toggle-button.anxiety-interference::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: repeating-linear-gradient(
          0deg,
          transparent,
          transparent 2px,
          rgba(100, 50, 50, 0.03) 2px,
          rgba(100, 50, 50, 0.03) 4px
        );
        animation: staticNoise 0.5s steps(10) infinite;
        pointer-events: none;
      }

      @keyframes moralePulse {
        0%, 100% { opacity: 0.7; transform: scale(1); }
        50% { opacity: 1; transform: scale(1.05); }
      }

      @keyframes staticNoise {
        0% { background-position: 0 0; }
        100% { background-position: 0 20px; }
      }

      .chat-window {
        position: fixed;
        bottom: 80px;
        right: 20px;
        width: 300px;
        max-height: 400px;
        background: #0a0a0f;
        border: 1px solid #1a1a2e;
        border-radius: 4px;
        color: #e0e0e0;
        font-family: 'Courier New', monospace;
        z-index: 1001;
        display: none;
        flex-direction: column;
        overflow: hidden;
        box-shadow: 0 0 20px rgba(0,0,0,0.5);
      }

      .chat-window.open {
        display: flex;
      }

      .chat-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 15px 20px;
        border-bottom: 1px solid #1a1a2e;
        background: #0c0c14;
      }

      .chat-title {
        font-size: 16px;
        font-weight: bold;
        color: #ffffff;
      }

      .chat-close-button {
        background: transparent;
        border: none;
        color: #e0e0e0;
        font-size: 18px;
        cursor: pointer;
        width: 24px;
        height: 24px;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .chat-close-button:hover {
        color: #ffffff;
      }

      .chat-messages {
        flex: 1;
        padding: 15px 20px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .chat-message {
        max-width: 80%;
        line-height: 1.5;
        padding: 8px 12px;
        border-radius: 4px;
        word-wrap: break-word;
      }

      .user-message {
        align-self: flex-end;
        background: #1a1a2e;
        border-left: 2px solid #ffd700;
      }

      .ai-message {
        align-self: flex-start;
        background: #0c0c14;
        border-left: 2px solid #4fc3f7;
      }

      .chat-input-container {
        display: flex;
        padding: 10px 20px;
        gap: 10px;
        border-top: 1px solid #1a1a2e;
      }

      #chat-input {
        flex: 1;
        padding: 10px;
        border: 1px solid #3a3a4c;
        background: #0a0a0f;
        color: #e0e0e0;
        border-radius: 4px;
        font-family: 'Courier New', monospace;
        font-size: 14px;
      }

      #chat-input:focus {
        outline: none;
        border-color: #4fc3f7;
        box-shadow: 0 0 8px rgba(79, 195, 247, 0.2);
      }

      #chat-send-button {
        padding: 0 15px;
        border: 1px solid #3a3a4c;
        background: transparent;
        color: #e0e0e0;
        border-radius: 4px;
        cursor: pointer;
        font-family: 'Courier New', monospace;
        font-size: 14px;
      }

      #chat-send-button:hover {
        border-color: #6a6a7c;
        color: #ffffff;
        background: rgba(255, 255, 255, 0.05);
      }

      /* Responsive adjustments */
      @media (max-width: 600px) {
        .chat-window {
          width: 90%;
          left: 5%;
          right: 5%;
          bottom: 10px;
          height: 50vh;
        }
        .chat-toggle-button {
          bottom: 10px;
          right: 10px;
        }
      }
    `;

    document.head.appendChild(style);
  }
};

// Make ChatAssistant globally available
window.ChatAssistant = ChatAssistant;