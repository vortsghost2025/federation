class DriftDetector {
  constructor({ driftThreshold = 0.2 } = {}) {
    this.driftThreshold = driftThreshold;
  }

  detect(reference, current) {
    if (!reference || reference.length === 0 || !current || current.length === 0) {
      return { status: 'UNKNOWN' };
    }
    const refMean = reference.reduce((a, b) => a + b, 0) / reference.length;
    const currMean = current.reduce((a, b) => a + b, 0) / current.length;
    const relativeDrift = Math.abs(currMean - refMean) / (refMean || 1);
    if (relativeDrift > this.driftThreshold) {
      return { status: 'DEGRADED', driftScore: relativeDrift };
    }
    return { status: 'HEALTHY', driftScore: relativeDrift };
  }
}

class NondeterminismScanner {
  constructor() {
    this.scanHistory = [];
  }

  scan(runResults) {
    const passRates = runResults.map(r => r.total > 0 ? r.passCount / r.total : 0);
    const isConsistent = passRates.every(rate => rate === passRates[0]);
    const hasFlake = runResults.some((r, i) => i > 0 && r.passCount !== runResults[0].passCount);
    return {
      status: hasFlake ? 'DEGRADED' : 'HEALTHY',
      passRates,
      isConsistent,
      scanCount: runResults.length
    };
  }
}

class VersionLedgerIntegrityChecker {
  constructor() {
    this.ledger = [];
  }

  verify(versionHistory) {
    const sorted = [...versionHistory].sort((a, b) => {
      if (a.modelId !== b.modelId) return a.modelId.localeCompare(b.modelId);
      return (a.version || 0) - (b.version || 0);
    });

    let hasGaps = false;
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i].modelId === sorted[i - 1].modelId && sorted[i].version - sorted[i - 1].version > 1) {
        hasGaps = true;
        break;
      }
    }
    return { status: hasGaps ? 'DEGRADED' : 'HEALTHY', gaps: hasGaps };
  }
}

class PrivacyAggregatorCorrectnessChecker {
  constructor() {
    this.checkHistory = [];
  }

  verify(privacyReport, secureSumSamples) {
    const isCompliant = privacyReport.status === 'COMPLIANT' && privacyReport.complianceRate === 100;
    const hasOutliers = secureSumSamples.some(s => s.outlierCount > 0);
    if (!isCompliant || hasOutliers) {
      return { status: 'DEGRADED', issues: ['compliance', 'outliers'] };
    }
    return { status: 'HEALTHY', issues: [] };
  }
}

class ConvergenceStabilityAnalyzer {
  constructor() {
    this.history = [];
  }

  analyze(convergenceHistory) {
    if (!convergenceHistory || convergenceHistory.length === 0) {
      return { status: 'UNKNOWN', trend: 'UNKNOWN' };
    }
    const n = convergenceHistory.length;
    const sum = convergenceHistory.reduce((a, b) => a + b, 0);
    const mean = sum / n;
    const variance = convergenceHistory.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) / n;

    let trend;
    if (n >= 2) {
      const firstHalf = convergenceHistory.slice(0, Math.floor(n / 2));
      const secondHalf = convergenceHistory.slice(Math.floor(n / 2));
      const firstMean = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length;
      const secondMean = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length;
      if (secondMean > firstMean) trend = 'IMPROVING';
      else if (secondMean < firstMean) trend = 'DEGRADING';
      else trend = 'STABLE';
    } else {
      trend = 'STABLE';
    }

    return {
      status: (trend === 'DEGRADING' || variance > 0.1) ? 'DEGRADED' : 'HEALTHY',
      trend,
      variance,
      mean
    };
  }
}

class OrchestrationLatencyMonitor {
  constructor({ maxP95LatencyMs = 250 } = {}) {
    this.maxP95LatencyMs = maxP95LatencyMs;
  }

  check(latencies) {
    if (!latencies || latencies.length === 0) {
      return { status: 'UNKNOWN', p95: 0 };
    }
    const sorted = [...latencies].sort((a, b) => a - b);
    const p95Index = Math.ceil(sorted.length * 0.95) - 1;
    const p95 = sorted[Math.max(0, p95Index)];

    return {
      status: p95 > this.maxP95LatencyMs ? 'DEGRADED' : 'HEALTHY',
      p95,
      maxAllowed: this.maxP95LatencyMs
    };
  }
}

class FederatedSelfDiagnosticsEngine {
  constructor() {
    this.runHistory = [];
    this.repairCount = 0;
  }

  runDiagnostics(input) {
    const driftDetector = new DriftDetector({ driftThreshold: 0.2 });
    const driftResult = driftDetector.detect(input.referenceMetrics || [], input.currentMetrics || []);

    const scanner = new NondeterminismScanner();
    const scanResult = scanner.scan(input.runResults || []);

    const ledger = new VersionLedgerIntegrityChecker();
    const ledgerResult = ledger.verify(input.versionHistory || []);

    const privacyChecker = new PrivacyAggregatorCorrectnessChecker();
    const privacyResult = privacyChecker.verify(input.privacyReport || { status: 'COMPLIANT', complianceRate: 100 }, input.secureSumSamples || []);

    const convergenceAnalyzer = new ConvergenceStabilityAnalyzer();
    const convergenceResult = convergenceAnalyzer.analyze(input.convergenceHistory || []);

    const latencyMonitor = new OrchestrationLatencyMonitor({ maxP95LatencyMs: 250 });
    const latencyResult = latencyMonitor.check(input.orchestrationLatencies || []);

    const isDegraded = driftResult.status === 'DEGRADED' ||
      scanResult.status === 'DEGRADED' ||
      ledgerResult.status === 'DEGRADED' ||
      privacyResult.status === 'DEGRADED' ||
      convergenceResult.status === 'DEGRADED' ||
      latencyResult.status === 'DEGRADED';

    const report = {
      drift: driftResult,
      nondeterminism: scanResult,
      ledger: ledgerResult,
      privacy: privacyResult,
      convergence: convergenceResult,
      latency: latencyResult,
      repairTriggered: isDegraded,
      timestamp: Date.now()
    };

    if (isDegraded) this.repairCount++;

    this.runHistory.push(report);
    return report;
  }

  getDiagnosticsStatus() {
    return {
      totalRuns: this.runHistory.length,
      repairsTriggered: this.repairCount,
      lastRun: this.runHistory[this.runHistory.length - 1]
    };
  }
}

export {
  DriftDetector,
  NondeterminismScanner,
  VersionLedgerIntegrityChecker,
  PrivacyAggregatorCorrectnessChecker,
  ConvergenceStabilityAnalyzer,
  OrchestrationLatencyMonitor,
  FederatedSelfDiagnosticsEngine
};
