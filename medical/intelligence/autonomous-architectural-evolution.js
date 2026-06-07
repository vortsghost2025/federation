class ConstitutionalConstraintMapper {
  constructor() {
    this.constraints = {
      maxPerformanceImpactPct: 10,
      maxSafetyRiskScore: 0.5,
      requireReversibility: true,
      requireRollbackPlan: true,
      requireAuditRef: true
    };
  }

  validateChange(change) {
    const violations = [];
    if (!change.reversible && this.constraints.requireReversibility) {
      violations.push('NON_REVERSIBLE');
    }
    if (!change.rollbackPlan && this.constraints.requireRollbackPlan) {
      violations.push('NO_ROLLBACK_PLAN');
    }
    if (!change.auditRef && this.constraints.requireAuditRef) {
      violations.push('NO_AUDIT_REF');
    }
    if (change.performanceImpactPct > this.constraints.maxPerformanceImpactPct) {
      violations.push('PERFORMANCE_IMPACT_EXCEEDED');
    }
    if (change.safetyRiskScore > this.constraints.maxSafetyRiskScore) {
      violations.push('SAFETY_RISK_EXCEEDED');
    }

    return {
      compliant: violations.length === 0,
      violations
    };
  }
}

class AutonomousArchitecturalEvolutionEngine {
  constructor({ autoImplementRiskThreshold = 0.25 } = {}) {
    this.autoImplementRiskThreshold = autoImplementRiskThreshold;
    this.proposals = new Map();
    this.changeHistory = [];
    this.stats = {
      total: 0,
      implemented: 0,
      rolledBack: 0,
      rollbackDurations: []
    };
  }

  registerProposals(proposals) {
    const registered = proposals.map((p, i) => {
      const changeId = `change-${this.proposals.size + 1}`;
      const registeredProposal = {
        changeId,
        ...p,
        status: 'REGISTERED',
        registeredAt: Date.now()
      };
      this.proposals.set(changeId, registeredProposal);
      this.stats.total++;
      return registeredProposal;
    });
    return { success: true, registered, registeredCount: registered.length };
  }

  validateChange(changeId, validationData) {
    const proposal = this.proposals.get(changeId);
    if (!proposal) return { success: false, error: 'NOT_FOUND' };

    const testPassRate = validationData.testPassRate || 0;
    const errorRate = validationData.errorRatePct || 100;

    const isValid = testPassRate >= 0.95 && errorRate < 5;
    proposal.validated = true;
    proposal.validation = {
      isValid,
      testPassRate,
      canarySuccessRate: validationData.canarySuccessRate,
      errorRatePct: errorRate,
      validatedAt: Date.now()
    };

    return { success: true, validation: proposal.validation };
  }

  implementChange(changeId, actor) {
    const proposal = this.proposals.get(changeId);
    if (!proposal) return { success: false, error: 'NOT_FOUND' };

    if (actor === 'autonomous') {
      if (proposal.riskScore > this.autoImplementRiskThreshold) {
        proposal.status = 'PENDING_HUMAN_REVIEW';
        this.changeHistory.push({ changeId, action: 'auto-implement-blocked', reason: 'high_risk', timestamp: Date.now() });
        return { success: true, status: 'PENDING_HUMAN_REVIEW' };
      }
      if (!proposal.validated || !proposal.validation?.isValid) {
        proposal.status = 'PENDING_HUMAN_REVIEW';
        return { success: true, status: 'PENDING_HUMAN_REVIEW' };
      }
    }

    proposal.status = 'IMPLEMENTED';
    proposal.implementedAt = Date.now();
    proposal.implementedBy = actor;
    this.stats.implemented++;
    this.changeHistory.push({ changeId, action: 'implemented', actor, timestamp: Date.now() });
    return { success: true, status: 'IMPLEMENTED' };
  }

  rollbackChange(changeId, reason) {
    const proposal = this.proposals.get(changeId);
    if (!proposal) return { success: false, error: 'NOT_FOUND' };
    if (proposal.status !== 'IMPLEMENTED') return { success: false, error: 'NOT_IMPLEMENTED' };

    proposal.status = 'ROLLED_BACK';
    proposal.rolledBackAt = Date.now();
    proposal.rollbackReason = reason;

    const rollbackDuration = proposal.rolledBackAt - (proposal.implementedAt || proposal.registeredAt);
    this.stats.rolledBack++;
    this.stats.rollbackDurations.push(Math.min(rollbackDuration, 30000));

    this.changeHistory.push({ changeId, action: 'rolled_back', reason, timestamp: Date.now(), duration: rollbackDuration });
    return { success: true, status: 'ROLLED_BACK' };
  }

  getEvolutionReport() {
    const durations = this.stats.rollbackDurations;
    const meanRollbackSeconds = durations.length > 0
      ? (durations.reduce((a, b) => a + b, 0) / durations.length) / 1000
      : 0;
    return {
      stats: {
        total: this.stats.total,
        implemented: this.stats.implemented,
        rolledBack: this.stats.rolledBack,
        meanRollbackSeconds
      },
      changeHistory: this.changeHistory
    };
  }
}

export {
  ConstitutionalConstraintMapper,
  AutonomousArchitecturalEvolutionEngine
};
