class ProposalLedger {
  constructor() {
    this.proposals = new Map();
  }

  addProposal(proposal) {
    this.proposals.set(proposal.proposalId, { ...proposal, status: 'PENDING' });
    return { success: true, proposal };
  }

  updateProposal(proposalId, updates) {
    const disallowedFields = ['proposalId', 'requiresHumanApproval', 'target'];
    const hasDisallowed = disallowedFields.some(f => f in updates);
    if (hasDisallowed) {
      return { success: false, error: 'DISALLOWED_UPDATE_FIELDS' };
    }
    const proposal = this.proposals.get(proposalId);
    if (!proposal) return { success: false };
    Object.assign(proposal, updates);
    return { success: true, proposal };
  }
}

class PatchProposalBuilder {
  constructor() {
    this.proposalCount = 0;
  }

  proposeCodePatch(target, summary, options = {}) {
    this.proposalCount++;
    return {
      proposalId: `code-patch-${this.proposalCount}-${Date.now()}`,
      type: 'CODE_PATCH',
      target,
      summary,
      expectedBenefit: options.expectedBenefit || 0.2,
      riskScore: options.riskScore || 0.2,
      highImpact: options.highImpact || false
    };
  }

  proposeTestImprovement(target, summary) {
    this.proposalCount++;
    return {
      proposalId: `test-improvement-${this.proposalCount}-${Date.now()}`,
      type: 'TEST_IMPROVEMENT',
      target,
      summary,
      expectedBenefit: 0.15,
      riskScore: 0.1
    };
  }

  proposeInvariant(target, summary) {
    this.proposalCount++;
    return {
      proposalId: `invariant-${this.proposalCount}-${Date.now()}`,
      type: 'INVARIANT',
      target,
      summary,
      expectedBenefit: 0.1,
      riskScore: 0.05
    };
  }

  proposeOptimization(target, summary) {
    this.proposalCount++;
    return {
      proposalId: `optimization-${this.proposalCount}-${Date.now()}`,
      type: 'OPTIMIZATION',
      target,
      summary,
      expectedBenefit: 0.2,
      riskScore: 0.15
    };
  }
}

class ProposalTester {
  constructor() {
    this.evaluationHistory = [];
  }

  evaluate(proposal, context) {
    const passRate = context.testPassRate || 0;
    const coverageDelta = context.coverageDelta || 0;
    const regressionRisk = context.regressionRisk || 1;

    let recommendation;
    if (passRate >= 0.95 && regressionRisk < 0.3 && coverageDelta >= 0) {
      recommendation = 'ACCEPT';
    } else if (passRate >= 0.8 && regressionRisk < 0.6) {
      recommendation = 'REVIEW';
    } else {
      recommendation = 'REJECT';
    }
    return { recommendation, proposal, context };
  }

  evaluateBatch(proposals, testContext) {
    const results = proposals.map(p => this.evaluate(p, testContext));
    const passed = results.filter(r => r.recommendation !== 'REJECT').length;
    return {
      total: results.length,
      passed,
      failed: results.length - passed,
      passRate: results.length > 0 ? passed / results.length : 0,
      avgScore: passed / results.length > 0 ? 85 : 20,
      results
    };
  }
}

class AutonomousPatchProposalEngine {
  constructor() {
    this.ledger = new ProposalLedger();
    this.builder = new PatchProposalBuilder();
    this.tester = new ProposalTester();
    this.proposals = new Map();
    this.proposalStats = { total: 0, accepted: 0, rejected: 0 };
  }

  proposeCodePatch(target, summary, options = {}) {
    const proposal = this.builder.proposeCodePatch(target, summary, options);
    this.ledger.addProposal(proposal);
    this.proposals.set(proposal.proposalId, proposal);
    this.proposalStats.total++;
    return { success: true, proposal };
  }

  proposeTestImprovement(target, summary) {
    const proposal = this.builder.proposeTestImprovement(target, summary);
    this.ledger.addProposal(proposal);
    this.proposals.set(proposal.proposalId, proposal);
    this.proposalStats.total++;
    return { success: true, proposal };
  }

  proposeInvariant(target, summary) {
    const proposal = this.builder.proposeInvariant(target, summary);
    this.ledger.addProposal(proposal);
    this.proposals.set(proposal.proposalId, proposal);
    this.proposalStats.total++;
    return { success: true, proposal };
  }

  proposeOptimization(target, summary) {
    const proposal = this.builder.proposeOptimization(target, summary);
    this.ledger.addProposal(proposal);
    this.proposals.set(proposal.proposalId, proposal);
    this.proposalStats.total++;
    return { success: true, proposal };
  }

  evaluateProposal(proposalId, context) {
    const proposal = this.proposals.get(proposalId) || this.ledger.proposals.get(proposalId);
    if (!proposal) return { success: false };

    const testPassRate = context.testPassRate || 0;
    const regressionRisk = context.regressionRisk || 0;

    if (proposal.highImpact || regressionRisk > 0.5) {
      return { success: true, status: 'PENDING_HUMAN_REVIEW', proposalId };
    }

    const evaluation = this.tester.evaluate(proposal, context);
    if (evaluation.recommendation === 'ACCEPT' || evaluation.recommendation === 'REVIEW') {
      this.proposalStats.accepted++;
      return { success: true, status: 'EVALUATED', proposalId, evaluation };
    }
    this.proposalStats.rejected++;
    return { success: true, status: 'REJECTED', proposalId, evaluation };
  }

  approveProposal(proposalId, approver) {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) return { success: false };
    proposal.status = 'APPROVED';
    proposal.approvedBy = approver;
    return { success: true };
  }

  markApplied(proposalId, details) {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) return { success: false };
    proposal.status = 'APPLIED';
    proposal.appliedAt = Date.now();
    proposal.appliedBy = details.mode;
    return { success: true };
  }

  rejectProposal(proposalId, reason) {
    const proposal = this.proposals.get(proposalId);
    if (!proposal) return { success: false };
    proposal.status = 'REJECTED';
    proposal.rejectReason = reason;
    this.proposalStats.rejected++;
    return { success: true };
  }

  proposeFromDiagnostics(diagnostics) {
    const proposals = [];
    if (diagnostics.nondeterminismScore > 0.2) {
      proposals.push(this.builder.proposeCodePatch('test-harness', 'Add repeated-run tests for flaky suites'));
    }
    if (diagnostics.orchestrationLatencyP95 > diagnostics.latencyBudgetMs) {
      proposals.push(this.builder.proposeOptimization('orchestrator', 'Reduce dispatch latency overhead'));
    }
    return { proposals, generatedCount: proposals.length };
  }

  getProposalReport() {
    return { stats: this.proposalStats, proposals: Array.from(this.proposals.values()) };
  }
}

export {
  ProposalLedger,
  PatchProposalBuilder,
  ProposalTester,
  AutonomousPatchProposalEngine
};
