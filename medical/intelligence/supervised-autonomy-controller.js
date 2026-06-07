class GuardrailPolicy {
  constructor() {
    this.forbiddenOperations = [];
    this.thresholds = {
      maxRiskScore: 0.5,
      maxLatencyRegressionPct: 10,
      minTestPassRate: 0.95
    };
  }

  evaluate(action) {
    const { riskScore, testPassRate, latencyRegressionPct, operations } = action;

    let blocked = false;
    let requiresHuman = false;
    const violations = [];

    for (const op of (operations || [])) {
      if (this.forbiddenOperations.includes(op)) {
        blocked = true;
        violations.push('FORBIDDEN_OPERATION');
      }
    }

    if (riskScore > this.thresholds.maxRiskScore) {
      requiresHuman = true;
      violations.push('HIGH_RISK');
    }

    if (testPassRate < this.thresholds.minTestPassRate) {
      blocked = true;
      violations.push('LOW_TEST_PASS_RATE');
    }

    if (latencyRegressionPct > this.thresholds.maxLatencyRegressionPct) {
      requiresHuman = true;
      violations.push('HIGH_LATENCY_REGRESSION');
    }

    return { blocked, requiresHuman, violations, allowed: !blocked && !requiresHuman };
  }

  setForbiddenOperations(operations) {
    this.forbiddenOperations = [...operations];
  }
}

class MutationZoneManager {
  constructor({ allowedZones = [] } = {}) {
    this.allowedZones = allowedZones;
  }

  evaluatePaths(filePaths) {
    for (const path of (filePaths || [])) {
      const normalized = path.replace(/\\/g, '/').replace(/\/+/g, '/');
      if (normalized.includes('..')) {
        return { allowed: false, reason: 'TRAVERSAL_DETECTED' };
      }
      const inAllowedZone = this.allowedZones.some(zone => normalized.startsWith(zone.replace(/\\/g, '/')));
      if (!inAllowedZone) {
        return { allowed: false, reason: 'OUTSIDE_ALLOWED_ZONE' };
      }
    }
    return { allowed: true };
  }
}

class AutonomyEscalationManager {
  constructor() {
    this.escalations = new Map();
    this.escalationCounter = 0;
  }

  createEscalation(action, reasons) {
    this.escalationCounter++;
    const escalationId = `esc-${this.escalationCounter}`;
    const escalation = {
      escalationId,
      action,
      reasons,
      status: 'PENDING',
      createdAt: Date.now()
    };
    this.escalations.set(escalationId, escalation);
    return escalation;
  }

  resolveEscalation(escalationId, resolution, resolvedBy) {
    const escalation = this.escalations.get(escalationId);
    if (!escalation) return { success: false };
    escalation.status = resolution;
    escalation.resolvedAt = Date.now();
    escalation.resolvedBy = resolvedBy;
    return { success: true, escalation };
  }

  getPendingEscalations() {
    return Array.from(this.escalations.values()).filter(e => e.status === 'PENDING');
  }
}

class SupervisedAutonomyController {
  constructor() {
    this.guardrails = new GuardrailPolicy();
    this.mutationZones = new MutationZoneManager({ allowedZones: [] });
    this.escalationManager = new AutonomyEscalationManager();
    this.decisionHistory = [];
  }

  configureMutationZones(zones) {
    this.mutationZones = new MutationZoneManager({ allowedZones: zones });
  }

  configureForbiddenOperations(operations) {
    this.guardrails.setForbiddenOperations(operations);
  }

  evaluateAction(action) {
    const allPaths = action.filePaths || [];
    const zoneEval = this.mutationZones.evaluatePaths(allPaths);

    if (!zoneEval.allowed) {
      this.decisionHistory.push({ actionId: action.actionId, decision: 'BLOCKED', reason: 'OUTSIDE_MUTATION_ZONE' });
      return { decision: 'BLOCKED', reason: zoneEval.reason };
    }

    const guardEval = this.guardrails.evaluate(action);

    if (guardEval.blocked) {
      this.decisionHistory.push({ actionId: action.actionId, decision: 'BLOCKED', reason: 'GUARDRAIL_VIOLATION' });
      return { decision: 'BLOCKED', reason: guardEval.violations.join(', ') };
    }

    if (guardEval.requiresHuman || action.highImpact) {
      const esc = this.escalationManager.createEscalation(action, guardEval.violations);
      this.decisionHistory.push({ actionId: action.actionId, decision: 'ESCALATE_HUMAN', escalationId: esc.escalationId });
      return { decision: 'ESCALATE_HUMAN', escalationId: esc.escalationId };
    }

    this.decisionHistory.push({ actionId: action.actionId, decision: 'AUTO_APPROVED' });
    return { decision: 'AUTO_APPROVED' };
  }

  getSupervisionStatus() {
    const totalDecisions = this.decisionHistory.length;
    const pendingEscalations = this.escalationManager.getPendingEscalations().length;
    return {
      totalDecisions,
      escalation: { pending: pendingEscalations }
    };
  }
}

export {
  GuardrailPolicy,
  MutationZoneManager,
  AutonomyEscalationManager,
  SupervisedAutonomyController
};
