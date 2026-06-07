class OutcomeMemoryStore {
  constructor() {
    this.outcomes = [];
    this.failures = [];
    this.instabilities = [];
    this.convergenceImprovements = [];
    this.nondeterminismCorrections = [];
  }

  recordOutcome(outcome) {
    this.outcomes.push({ ...outcome, recordedAt: Date.now() });
  }

  recordFailure(failure) {
    this.failures.push({ ...failure, recordedAt: Date.now() });
  }

  recordInstability(instability) {
    this.instabilities.push({ ...instability, recordedAt: Date.now() });
  }

  recordConvergenceImprovement(cycleId, before, after) {
    this.convergenceImprovements.push({ cycleId, before, after, recordedAt: Date.now() });
  }

  recordNondeterminismCorrection(cycleId, suite, strategy) {
    this.nondeterminismCorrections.push({ cycleId, suite, strategy, recordedAt: Date.now() });
  }
}

class FailurePatternAnalyzer {
  constructor() {
    this.analysisHistory = [];
  }

  analyzeFailures(failures) {
    const bySubsystem = {};
    const byReason = {};
    let totalFailures = failures.length;

    for (const failure of failures) {
      const sub = failure.subsystem || 'unknown';
      bySubsystem[sub] = (bySubsystem[sub] || 0) + 1;
      const reason = failure.reason || 'unknown';
      byReason[reason] = (byReason[reason] || 0) + 1;
    }

    const hotZones = Object.entries(bySubsystem)
      .filter(([, count]) => count >= 1)
      .map(([subsystem, count]) => ({ subsystem, count }));

    return {
      totalFailures,
      bySubsystem,
      byReason,
      hotZones,
      analyzedAt: Date.now()
    };
  }
}

class LongHorizonEvolutionMemoryEngine {
  constructor() {
    this.store = new OutcomeMemoryStore();
    this.analyzer = new FailurePatternAnalyzer();
  }

  recordOutcome(cycleId, proposalId, outcome, metadata = {}) {
    this.store.recordOutcome({ cycleId, proposalId, outcome, metadata });
  }

  recordFailure(cycleId, proposalId, reason, subsystem) {
    this.store.recordFailure({ cycleId, proposalId, reason, subsystem });
  }

  recordInstability(cycleId, cause, impactScore) {
    this.store.recordInstability({ cycleId, cause, impactScore });
  }

  recordConvergenceImprovement(cycleId, before, after) {
    this.store.recordConvergenceImprovement(cycleId, before, after);
  }

  recordNondeterminismCorrection(cycleId, suite, strategy) {
    this.store.recordNondeterminismCorrection(cycleId, suite, strategy);
  }

  getWhatWorked() {
    return this.store.outcomes.filter(o => o.outcome === 'SUCCESS');
  }

  getInstitutionalMemoryReport() {
    const successCount = this.store.outcomes.filter(o => o.outcome === 'SUCCESS').length;
    const failurePatterns = this.analyzer.analyzeFailures(this.store.failures);
    const recommendations = [];

    if (this.store.failures.length > 0) {
      recommendations.push('Investigate recurring failure patterns');
    }
    if (this.store.convergenceImprovements.length > 0) {
      recommendations.push('Apply convergence improvement strategies to new cycles');
    }
    if (this.store.nondeterminismCorrections.length > 0) {
      recommendations.push('Enforce nondeterminism corrections as standard procedure');
    }
    if (recommendations.length === 0) {
      recommendations.push('Continue current approach as no failures have been recorded');
    }

    return {
      totals: {
        outcomes: this.store.outcomes.length,
        failures: this.store.failures.length,
        instabilities: this.store.instabilities.length,
        successRate: this.store.outcomes.length > 0 ? successCount / this.store.outcomes.length : 1
      },
      failurePatterns,
      recommendations
    };
  }
}

export {
  OutcomeMemoryStore,
  FailurePatternAnalyzer,
  LongHorizonEvolutionMemoryEngine
};
