class SelfArchitectureModel {
  constructor() {
    this.components = [];
    this.interfaces = [];
    this.invariants = [];
  }

  ingestSnapshot(snapshot) {
    this.components = [...(snapshot.components || [])];
    this.interfaces = [...(snapshot.interfaces || [])];
    this.invariants = [...(snapshot.invariants || [])];
    return {
      success: true,
      componentCount: this.components.length,
      interfaceCount: this.interfaces.length,
      invariantCount: this.invariants.length
    };
  }

  computeConsistency(externalInspection) {
    const extComps = new Set(externalInspection.components || []);
    const localComps = new Set(this.components.map(c => c.componentId));

    let matchingComponents = 0;
    for (const c of extComps) {
      if (localComps.has(c)) matchingComponents++;
    }

    const compScore = extComps.size > 0 ? matchingComponents / extComps.size : 1;

    const extInterfaces = new Set(externalInspection.interfaces || []);
    const localInterfaces = new Set(this.interfaces.map(i => i.interfaceId));
    let matchingInterfaces = 0;
    for (const iface of extInterfaces) {
      if (localInterfaces.has(iface)) matchingInterfaces++;
    }
    const ifaceScore = extInterfaces.size > 0 ? matchingInterfaces / extInterfaces.size : 1;

    const extInvariants = new Set(externalInspection.invariants || []);
    const localInvariants = new Set(this.invariants);
    let matchingInvariants = 0;
    for (const inv of extInvariants) {
      if (localInvariants.has(inv)) matchingInvariants++;
    }
    const invScore = extInvariants.size > 0 ? matchingInvariants / extInvariants.size : 1;

    const consistency = (compScore + ifaceScore + invScore) / 3;
    return { consistency, componentScore: compScore, interfaceScore: ifaceScore, invariantScore: invScore };
  }
}

class ArchitecturalReasoner {
  constructor() {
    this.proposalHistory = [];
  }

  proposeChanges(selfModel, telemetry) {
    const { consistency, decisionOscillationScore, validationBacklog, traceabilityCoverage, learningEfficiencyTrend } = telemetry;

    const proposals = [];
    if (decisionOscillationScore > 0) {
      proposals.push({
        type: 'DECISION_STABILIZATION',
        target: 'decision-pipeline',
        summary: 'Reduce decision oscillation',
        expectedBenefit: 0.3,
        riskScore: 0.2
      });
    }
    if (validationBacklog > 0) {
      proposals.push({
        type: 'VALIDATION_BACKLOG_REDUCTION',
        target: 'validation-harness',
        summary: 'Reduce validation backlog',
        expectedBenefit: 0.25,
        riskScore: 0.15
      });
    }
    if (traceabilityCoverage < 1) {
      proposals.push({
        type: 'TRACEABILITY_ENHANCEMENT',
        target: 'audit-system',
        summary: 'Improve traceability coverage',
        expectedBenefit: 0.2,
        riskScore: 0.1
      });
    }
    if (learningEfficiencyTrend < 0) {
      proposals.push({
        type: 'LEARNING_EFFICIENCY_RECOVERY',
        target: 'meta-learning',
        summary: 'Recover declining learning efficiency',
        expectedBenefit: 0.25,
        riskScore: 0.2
      });
    }

    if (proposals.length === 0) {
      proposals.push({
        type: 'ARCHITECTURE_HYGIENE_SWEEP',
        target: 'system',
        summary: 'General architecture hygiene',
        expectedBenefit: 0.05,
        riskScore: 0.05
      });
    }

    this.proposalHistory.push({ proposals, telemetry });
    return proposals;
  }
}

class MetaCognitiveAwarenessEngine {
  constructor() {
    this.selfModel = new SelfArchitectureModel();
    this.reasoner = new ArchitecturalReasoner();
    this.scanHistory = [];
    this.reflectionHistory = [];
  }

  scanArchitecture(snapshot, externalInspection) {
    const ingest = this.selfModel.ingestSnapshot(snapshot);
    const consistency = this.selfModel.computeConsistency(externalInspection);
    const result = { success: true, componentCount: ingest.componentCount, consistency: consistency.consistency };
    this.scanHistory.push(result);
    return result;
  }

  reflectOnCognition(telemetry) {
    const oscillation = telemetry.decisions ? this._computeOscillation(telemetry.decisions) : 0;
    const result = {
      decisionOscillationScore: oscillation,
      validationBacklog: telemetry.validationBacklog || 0,
      traceabilityCoverage: telemetry.traceabilityCoverage || 0,
      learningEfficiencyTrend: telemetry.learningEfficiencyTrend || 0
    };
    this.reflectionHistory.push({ ...telemetry, oscillation });
    return result;
  }

  _computeOscillation(decisions) {
    if (!decisions || decisions.length < 2) return 0;
    let changes = 0;
    for (let i = 1; i < decisions.length; i++) {
      if (decisions[i] !== decisions[i - 1]) changes++;
    }
    return changes / (decisions.length - 1);
  }

  proposeSelfArchitectureChanges(input) {
    const telemetry = {
      consistency: 0.9,
      decisionOscillationScore: this.reflectionHistory.length > 0 ? this.reflectionHistory[this.reflectionHistory.length - 1].decisionOscillationScore : 0,
      validationBacklog: input?.validationBacklog || this.reflectionHistory.length > 0 ? this.reflectionHistory[this.reflectionHistory.length - 1].validationBacklog : 0,
      traceabilityCoverage: input?.traceabilityCoverage || 0.75,
      learningEfficiencyTrend: input?.learningEfficiencyTrend || -0.05
    };
    const proposals = this.reasoner.proposeChanges({ consistency: 0.9 }, telemetry);
    return {
      proposalCount: proposals.length,
      proposals,
      telemetry
    };
  }
}

export {
  SelfArchitectureModel,
  ArchitecturalReasoner,
  MetaCognitiveAwarenessEngine
};
