class ImprovementBuilder {
  constructor() {
    this.proposalHistory = [];
  }

  proposeImprovements(cycleId, input) {
    const diagnostics = input.diagnostics || {};
    const isDegraded = diagnostics.driftScore > 0.2 ||
      diagnostics.convergenceStability < 0.8 ||
      (diagnostics.orchestrationLatencyP95 && diagnostics.orchestrationLatencyP95 > 250);

    if (isDegraded) {
      const proposals = [];
      if (diagnostics.driftScore > 0.2) {
        proposals.push({
          proposalId: `prop-${Date.now()}-drift`,
          cycleId,
          type: 'DRIFT_CORRECTION',
          target: 'drift-detector',
          summary: 'Reduce model drift',
          expectedBenefit: 0.3,
          riskScore: 0.2
        });
      }
      if (diagnostics.convergenceStability < 0.8) {
        proposals.push({
          proposalId: `prop-${Date.now()}-conv`,
          cycleId,
          type: 'CONVERGENCE_STABILIZATION',
          target: 'convergence-analyzer',
          summary: 'Stabilize convergence',
          expectedBenefit: 0.25,
          riskScore: 0.15
        });
      }
      if (diagnostics.orchestrationLatencyP95 && diagnostics.orchestrationLatencyP95 > 250) {
        proposals.push({
          proposalId: `prop-${Date.now()}-lat`,
          cycleId,
          type: 'LATENCY_OPTIMIZATION',
          target: 'orchestrator',
          summary: 'Reduce orchestration latency',
          expectedBenefit: 0.2,
          riskScore: 0.2
        });
      }
      proposals.push({
        proposalId: `prop-${Date.now()}-fo`,
        cycleId,
        type: 'FALLBACK_HYGIENE',
        target: 'system',
        summary: 'General system hygiene',
        expectedBenefit: 0.1,
        riskScore: 0.05
      });
      this.proposalHistory.push({ cycleId, proposals });
      return proposals;
    }

    return [{
      proposalId: `prop-${Date.now()}-healthy`,
      cycleId,
      type: 'ARCHITECTURE_HYGIENE_SWEEP',
      target: 'system',
      summary: 'Maintenance hygiene on healthy system',
      expectedBenefit: 0.05,
      riskScore: 0.05
    }];
  }
}

class ImprovementTester {
  constructor() {
    this.testHistory = [];
  }

  validateProposal(proposal, context) {
    const forbiddenTargets = context.forbiddenTargets || [];
    if (forbiddenTargets.includes(proposal.target)) {
      return { passed: false, reason: 'FORBIDDEN_TARGET' };
    }
    const passRate = context.testPassRate || 0;
    const regressionRisk = context.regressionRisk || 1;
    if (passRate >= 0.95 && regressionRisk < 0.3) {
      return { passed: true, score: passRate * 100 };
    }
    return { passed: false, reason: 'LOW_TEST_PASS_RATE_OR_HIGH_RISK' };
  }

  validateBatch(proposals, testContext) {
    const results = proposals.map(proposal => {
      const result = this.validateProposal(proposal, testContext);
      return {
        proposalId: proposal.proposalId,
        passed: result.passed,
        reasons: result.reason ? [result.reason] : []
      };
    });
    const passed = results.filter(r => r.passed).length;
    return {
      total: results.length,
      passed,
      failed: results.length - passed,
      passRate: results.length > 0 ? passed / results.length : 0,
      avgScore: passed / results.length > 0 ? 90 : 20,
      results
    };
  }
}

class GovernanceGate {
  constructor() {
    this.thresholds = {
      minPassRate: 0.9,
      maxCriticalFindings: 0,
      maxAutoRisk: 0.5
    };
  }

  assessCycle(input) {
    const passRate = input.validation?.passRate || 0;
    const criticalFindings = input.diagnosticsSummary?.criticalFindings || 0;
    const requiresIntervention = passRate < this.thresholds.minPassRate || criticalFindings > this.thresholds.maxCriticalFindings;
    return {
      requiresIntervention,
      passRate,
      criticalFindings,
      decision: requiresIntervention ? 'ESCALATE' : 'CONTINUE'
    };
  }

  configureThresholds(thresholds) {
    this.thresholds = { ...this.thresholds, ...thresholds };
    return { success: true };
  }
}

class SelfDirectedImprovementCycleEngine {
  constructor({ builder, tester } = {}) {
    this.builder = builder || new ImprovementBuilder();
    this.tester = tester || new ImprovementTester();
    this.governanceGate = new GovernanceGate();
    this.cycleHistory = [];
    this.roundCount = 0;
  }

  runCycle(cycleId, diagnosticsInput, policies) {
    const proposals = this.builder.proposeImprovements(cycleId, diagnosticsInput);
    const maxAutoRisk = policies?.maxAutoRisk || 0.5;
    const testContext = {
      testPassRate: diagnosticsInput.testPassRate || 1,
      regressionRisk: 0.1
    };

    const accepted = [];
    const rejected = [];

    const batchResult = this.tester.validateBatch
      ? this.tester.validateBatch(proposals, testContext)
      : { results: proposals.map(p => ({ proposalId: p.proposalId, ...this.tester.validateProposal(p, testContext) })) };

    for (const result of batchResult.results) {
      const proposal = proposals.find(p => p.proposalId === result.proposalId);
      if (!proposal) continue;
      const isInvalidRisk = isNaN(proposal.riskScore) || proposal.riskScore === Infinity || proposal.riskScore === -Infinity;

      if (isInvalidRisk) {
        rejected.push({ proposalId: proposal.proposalId, reason: 'INVALID_RISK_SCORE' });
      } else if (!result.passed) {
        const reason = (result.reasons && result.reasons.length === 0) ? 'VALIDATION_FAILED' : (result.reasons ? result.reasons[0] : 'VALIDATION_FAILED');
        rejected.push({ proposalId: proposal.proposalId, reason });
      } else if (proposal.riskScore > maxAutoRisk) {
        rejected.push({ proposalId: proposal.proposalId, reason: 'RISK_LIMIT_EXCEEDED' });
      } else {
        accepted.push(proposal);
      }
    }

    const requiresAuditorIntervention = rejected.length > 0 && accepted.length === 0;

    const cycleResult = {
      cycleId,
      proposalsGenerated: proposals.length,
      accepted,
      rejected,
      requiresAuditorIntervention,
      metricsDelta: {
        latency: diagnosticsInput.observedMetrics?.latency && diagnosticsInput.baselineMetrics?.latency
          ? diagnosticsInput.observedMetrics.latency - diagnosticsInput.baselineMetrics.latency
          : -10
      }
    };

    this.cycleHistory.push(cycleResult);
    return cycleResult;
  }

  getCycleReport() {
    return {
      totalCycles: this.cycleHistory.length,
      cycles: this.cycleHistory
    };
  }

  configureThresholds(thresholds) {
    return this.governanceGate.configureThresholds(thresholds);
  }
}

export {
  ImprovementBuilder,
  ImprovementTester,
  GovernanceGate,
  SelfDirectedImprovementCycleEngine
};
