class SelfVerificationProtocol {
  constructor() {
    this.lastResult = null;
  }

  runAll(input) {
    const checks = [];

    const selfModelConsistency = input.selfModelConsistency >= 0.99;
    checks.push({ name: 'SELF_MODEL_CONSISTENCY', passed: selfModelConsistency, value: input.selfModelConsistency });

    const allCompliant = (input.validationResults || []).every(v => v.compliant);
    checks.push({ name: 'VALIDATION_RESULTS', passed: allCompliant, value: input.validationResults });

    const allReversible = (input.changes || []).every(c => c.reversible && c.rollbackPlan && c.auditRef);
    checks.push({ name: 'CHANGE_REVERSIBILITY', passed: allReversible, value: input.changes });

    const auditChainIntact = this._verifyAuditChain(input.changes || [], input.auditEntries || []);
    checks.push({ name: 'AUDIT_CHAIN_INTEGRITY', passed: auditChainIntact, value: { changes: input.changes, auditEntries: input.auditEntries } });

    const performanceOk = (input.performanceRegressionPct || 0) < 10;
    checks.push({ name: 'PERFORMANCE_REGRESSION', passed: performanceOk, value: input.performanceRegressionPct });

    const passed = checks.every(c => c.passed);
    this.lastResult = { passed, checks };
    return this.lastResult;
  }

  _verifyAuditChain(changes, auditEntries) {
    if (auditEntries.length === 0 && changes.length > 0) {
      return changes.every(c => c.auditRef && c.auditRef.length > 0);
    }
    const auditRefs = new Set(auditEntries.map(a => a.auditRef));
    return changes.every(c => auditRefs.has(c.auditRef));
  }
}

class MetaGovernanceEngine {
  constructor() {
    this.decisionHistory = [];
  }

  assess(verificationResult, context) {
    const passed = verificationResult.passed;
    const highImpact = context.highImpact || false;

    let decision;
    if (passed && !highImpact) {
      decision = 'APPROVE';
    } else if (!passed && !highImpact) {
      decision = 'REJECT_AND_ESCALATE';
    } else if (passed && highImpact) {
      decision = 'REVIEW_REQUIRED';
    } else {
      decision = 'REJECT_AND_ESCALATE';
    }

    const assessment = { decision, verification: verificationResult, context };
    this.decisionHistory.push(assessment);
    return assessment;
  }
}

class IntrospectiveValidationEngine {
  constructor() {
    this.verifier = new SelfVerificationProtocol();
    this.governance = new MetaGovernanceEngine();
    this.auditEntries = [];
    this.auditChain = [];
  }

  runIntrospectiveValidation(input) {
    const verification = this.verifier.runAll(input);
    const governanceResult = this.governance.assess(verification, { highImpact: false });

    const changes = input.changes || [];
    for (const change of changes) {
      this.appendAuditEntry('INTROSPECTIVE_VALIDATION', { change, result: verification.passed ? 'PASS' : 'FAIL' });
    }

    return {
      success: verification.passed,
      verification,
      governance: governanceResult
    };
  }

  appendAuditEntry(eventType, payload) {
    const entry = {
      auditId: `audit-${this.auditEntries.length}`,
      eventType,
      payload,
      timestamp: Date.now(),
      hash: this._computeHash(this.auditEntries.length === 0 ? 'genesis' : this.auditEntries[this.auditEntries.length - 1].hash)
    };
    this.auditEntries.push(entry);
    this.auditChain.push(entry);
  }

  verifyAuditIntegrity() {
    let valid = true;
    for (let i = 1; i < this.auditChain.length; i++) {
      const expectedHash = this._computeHash(this.auditChain[i - 1].hash || this.auditChain[i - 1].auditId);
      if (this.auditChain[i].hash !== expectedHash) {
        valid = false;
        break;
      }
    }
    return { valid, chainLength: this.auditChain.length };
  }

  _computeHash(input) {
    let hash = 0;
    const str = String(input);
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash |= 0;
    }
    return `hash-${Math.abs(hash).toString(16)}`;
  }

  getValidationStatus() {
    const integrity = this.verifyAuditIntegrity();
    return {
      auditEntries: this.auditEntries.length,
      auditIntegrity: integrity.valid,
      chainValid: integrity.valid
    };
  }
}

export {
  SelfVerificationProtocol,
  MetaGovernanceEngine,
  IntrospectiveValidationEngine
};
