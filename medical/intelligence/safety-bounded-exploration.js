class SafetyConstraintEngine {
  constructor() {
    this.constraints = {
      maxRiskScore: 1,
      maxLatencyRegressionPct: 15,
      maxFailureRateIncreasePct: 10
    };
    this.allowedStrategies = new Set(['ALT_AGGREGATION', 'STRICT_CONVERGENCE', 'PARALLEL_VALIDATION', 'STANDARD']);
  }

  evaluateExperiment(experiment) {
    const { type, riskScore, operations } = experiment;

    if (!this.allowedStrategies.has(type)) {
      return { allowed: false, reason: 'UNKNOWN_STRATEGY' };
    }

    if (riskScore > this.constraints.maxRiskScore) {
      return { allowed: false, reason: 'RISK_SCORE_EXCEEDED' };
    }

    const forbiddenOps = operations.filter(op => {
      return op !== undefined;
    });

    return { allowed: true };
  }

  updateConstraints(newConstraints) {
    if (newConstraints.maxRiskScore != null) {
      this.constraints.maxRiskScore = Math.max(0, Math.min(1, newConstraints.maxRiskScore));
    }
    if (newConstraints.maxLatencyRegressionPct != null) {
      this.constraints.maxLatencyRegressionPct = Math.max(0, newConstraints.maxLatencyRegressionPct);
    }
    if (newConstraints.maxFailureRateIncreasePct != null) {
      this.constraints.maxFailureRateIncreasePct = Math.max(0, Math.min(100, newConstraints.maxFailureRateIncreasePct));
    }
  }

  getConstraints() {
    return { ...this.constraints };
  }
}

class RollbackManager {
  constructor() {
    this.checkpoints = new Map();
  }

  createCheckpoint(experimentId, state) {
    this.checkpoints.set(experimentId, {
      experimentId,
      state: { ...state },
      createdAt: Date.now()
    });
  }

  rollback(experimentId, reason) {
    const checkpoint = this.checkpoints.get(experimentId);
    if (!checkpoint) return { success: false };
    return {
      success: true,
      restoredState: { ...checkpoint.state },
      reason,
      rolledBackAt: Date.now()
    };
  }

  getRollbackStats() {
    return { totalCheckpoints: this.checkpoints.size };
  }
}

class ExplorationSandbox {
  constructor() {
    this.simulationHistory = [];
  }

  simulate(experiment, metrics) {
    const strategy = experiment.type || 'STANDARD';
    let latencyMultiplier = 1;
    if (strategy === 'STRICT_CONVERGENCE') {
      latencyMultiplier = 1.05;
    } else {
      latencyMultiplier = 0.95 + Math.random() * 0.04;
    }
    const failureMultiplier = strategy === 'STRICT_CONVERGENCE' ? 1.2 : (0.8 + Math.random() * 0.4);
    const simulatedMetrics = {
      convergenceScore: metrics.convergenceScore * (0.8 + Math.random() * 0.4),
      orchestrationLatencyP95: metrics.orchestrationLatencyP95 * latencyMultiplier,
      failureRate: Math.max(0, metrics.failureRate * failureMultiplier),
      mergeConflictRate: metrics.mergeConflictRate * (0.5 + Math.random() * 0.5)
    };
    this.simulationHistory.push({ experiment, simulatedMetrics, timestamp: Date.now() });
    return { simulatedMetrics };
  }
}

class SafetyBoundedExplorationEngine {
  constructor() {
    this.explorationHistory = [];
    this.constraints = {
      forbiddenOperations: [],
      maxLatencyRegressionPct: 10,
      maxFailureRateIncreasePct: 10
    };
    this.rollbackManager = new RollbackManager();
    this.exploredExperiments = new Map();
  }

  configureConstraints(newConstraints) {
    if (newConstraints.forbiddenOperations) {
      this.constraints.forbiddenOperations = [...newConstraints.forbiddenOperations];
    }
    if (newConstraints.maxLatencyRegressionPct !== undefined) {
      this.constraints.maxLatencyRegressionPct = Math.max(0, newConstraints.maxLatencyRegressionPct);
    }
    if (newConstraints.maxFailureRateIncreasePct !== undefined) {
      this.constraints.maxFailureRateIncreasePct = Math.max(0, newConstraints.maxFailureRateIncreasePct);
    }
  }

  explore(experimentId, experiment, baselineMetrics) {
    const constraintEngine = new SafetyConstraintEngine();
    constraintEngine.constraints = { ...this.constraints };

    if (experiment.operations) {
      for (const op of experiment.operations) {
        if (this.constraints.forbiddenOperations.includes(op)) {
          this.explorationHistory.push({ experimentId, status: 'BLOCKED', reason: 'FORBIDDEN_OPERATION' });
          return { status: 'BLOCKED', experimentId };
        }
      }
    }

    if (experiment.riskScore > constraintEngine.constraints.maxRiskScore) {
      this.explorationHistory.push({ experimentId, status: 'BLOCKED', reason: 'RISK_EXCEEDED' });
      return { status: 'BLOCKED', experimentId };
    }

    const sandbox = new ExplorationSandbox();
    const sim = sandbox.simulate(experiment, baselineMetrics);

    const latencyRegression = (baselineMetrics.orchestrationLatencyP95 - sim.simulatedMetrics.orchestrationLatencyP95) / baselineMetrics.orchestrationLatencyP95;
    const actualLatencyPct = (sim.simulatedMetrics.orchestrationLatencyP95 - baselineMetrics.orchestrationLatencyP95) / baselineMetrics.orchestrationLatencyP95 * 100;

    if (actualLatencyPct > this.constraints.maxLatencyRegressionPct && this.constraints.maxLatencyRegressionPct >= 0) {
      this.rollbackManager.createCheckpoint(experimentId, baselineMetrics);
      this.explorationHistory.push({ experimentId, status: 'ROLLED_BACK', reason: 'LATENCY_REGRESSION' });
      return { status: 'ROLLED_BACK', experimentId, reason: 'LATENCY_REGRESSION' };
    }

    this.exploredExperiments.set(experimentId, { experiment, result: sim, status: 'ACCEPTED' });
    this.explorationHistory.push({ experimentId, status: 'ACCEPTED' });
    return { status: 'ACCEPTED_IN_SANDBOX', experimentId, simulatedMetrics: sim.simulatedMetrics };
  }

  getExplorationStatus() {
    const accepted = this.explorationHistory.filter(e => e.status === 'ACCEPTED' || e.status === 'ACCEPTED_IN_SANDBOX').length;
    const blocked = this.explorationHistory.filter(e => e.status === 'BLOCKED').length;
    const rolledBack = this.explorationHistory.filter(e => e.status === 'ROLLED_BACK').length;
    return {
      totalExperiments: this.explorationHistory.length,
      accepted,
      blocked,
      rolledBack,
      rollbackStats: { rollbacks: rolledBack }
    };
  }
}

export {
  SafetyConstraintEngine,
  RollbackManager,
  ExplorationSandbox,
  SafetyBoundedExplorationEngine
};
