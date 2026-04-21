#!/usr/bin/env python3
"""
Enhanced Live Trading Monitor with Detailed Agent Status
Shows real-time agent workflow, thresholds, and decision process
"""
import time
import json
from datetime import datetime
from pathlib import Path

def read_events():
    """Read all events from logs/events.jsonl"""
    events_file = Path("logs/events.jsonl")
    if not events_file.exists():
        return []
    
    events = []
    with open(events_file, 'r') as f:
        for line in f:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except:
                    pass
    return events

def progress_bar(value, max_value, width=30, label=""):
    """Create a visual progress bar"""
    pct = min(100, (value / max_value * 100) if max_value > 0 else 0)
    filled = int(width * pct / 100)
    bar = '█' * filled + '░' * (width - filled)
    return f"{label}{bar} {pct:.1f}%"

def threshold_indicator(value, threshold, label="", inverse=False):
    """Show if value meets threshold with visual indicator"""
    if inverse:
        meets = value <= threshold
        symbol = "✓" if meets else "✗"
        color = "✅" if meets else "⚠️"
    else:
        meets = value >= threshold
        symbol = "✓" if meets else "✗"
        color = "✅" if meets else "⚠️"
    
    return f"{color} {label}: {value:.3f} (threshold: {threshold}) {symbol}"

def monitor_live_detailed():
    """Monitor live trading with detailed agent status"""
    print("=" * 100)
    print("🔴 LIVE TRADING MONITOR - DETAILED AGENT STATUS VIEW")
    print("=" * 100)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Capital: $100 | Max Risk: $1/trade | Pair: SOL/USDT")
    print("=" * 100)
    print()
    
    start_time = time.time()
    initial_balance = 100.0
    current_balance = initial_balance
    daily_risk_limit = 5.0  # 5% of $100
    daily_risk_used = 0.0
    
    trades_executed = 0
    wins = 0
    losses = 0
    total_profit = 0.0
    
    risk_violations = 0
    api_errors = 0
    exchange_rejections = 0
    
    last_event_count = 0
    cycle_count = 0
    
    # Agent phase tracking
    current_phase = "Waiting for signal..."
    last_analysis = {}
    
    while True:
        elapsed = time.time() - start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        cycle_count += 1
        
        # Read new events
        events = read_events()
        new_events = events[last_event_count:]
        last_event_count = len(events)
        
        # Process new events
        for event in new_events:
            event_type = event.get('event_type', '')
            data = event.get('data', {})
            
            if event_type == 'market_analysis':
                last_analysis = data
                current_phase = f"Analyzing: {data.get('symbol', 'N/A')}"
            
            elif event_type == 'risk_evaluation':
                current_phase = f"Risk Check: {data.get('symbol', 'N/A')}"
            
            elif event_type == 'backtest_result':
                current_phase = f"Backtest: {data.get('symbol', 'N/A')}"
            
            elif event_type == 'trade_executed':
                trades_executed += 1
                profit = data.get('profit', 0)
                risk_used = data.get('risk_amount', 0)
                total_profit += profit
                current_balance += profit
                daily_risk_used += risk_used
                
                if profit > 0:
                    wins += 1
                else:
                    losses += 1
                
                current_phase = f"Trade #{trades_executed} executed: ${profit:+.2f}"
            
            elif event_type == 'risk_violation':
                risk_violations += 1
                print(f"\n⚠️ RISK VIOLATION: {data}\n")
            
            elif event_type == 'api_error':
                api_errors += 1
                print(f"\n❌ API ERROR: {data}\n")
            
            elif event_type == 'order_rejected':
                exchange_rejections += 1
                print(f"\n❌ EXCHANGE REJECTION: {data}\n")
        
        # Calculate stats
        win_rate = (wins / trades_executed * 100) if trades_executed > 0 else 0
        profit_pct = ((current_balance - initial_balance) / initial_balance * 100)
        risk_pct = (daily_risk_used / daily_risk_limit * 100)
        
        # Clear screen area and print dashboard
        print(f"\r⏱️  {hours:02d}:{minutes:02d}:{seconds:02d} | Cycle {cycle_count} | {current_phase:<50}", end='')
        print(f"\n")
        print(f"┌{'─'*98}┐")
        print(f"│ {'ACCOUNT STATUS':<96} │")
        print(f"├{'─'*98}┤")
        print(f"│ Balance: ${current_balance:>7.2f} | P&L: ${total_profit:>+7.2f} ({profit_pct:>+6.2f}%) | Trades: {trades_executed:>3} | Win Rate: {win_rate:>5.1f}% │")
        print(f"│ {progress_bar(daily_risk_used, daily_risk_limit, 40, 'Daily Risk: '):<96} │")
        print(f"└{'─'*98}┘")
        
        # Show last analysis if available
        if last_analysis:
            print(f"┌{'─'*98}┐")
            print(f"│ {'LAST MARKET ANALYSIS':<96} │")
            print(f"├{'─'*98}┤")
            
            symbol = last_analysis.get('symbol', 'N/A')
            signal = last_analysis.get('signal', 'N/A')
            strength = last_analysis.get('strength', 0)
            regime = last_analysis.get('regime', 'N/A')
            
            print(f"│ Symbol: {symbol:<20} | Signal: {signal:<8} | Strength: {strength:>6.3f} | Regime: {regime:<12} │")
            
            # Show threshold checks
            signal_threshold = 0.10
            win_rate_threshold = 0.45
            
            meets_signal = strength >= signal_threshold
            signal_symbol = "✅" if meets_signal else "⚠️"
            
            print(f"│ {signal_symbol} Signal Strength: {strength:.3f} {'≥' if meets_signal else '<'} {signal_threshold} (threshold)                                  │")
            
            if 'win_rate' in last_analysis:
                win_rate_check = last_analysis['win_rate']
                meets_winrate = win_rate_check >= win_rate_threshold
                winrate_symbol = "✅" if meets_winrate else "⚠️"
                print(f"│ {winrate_symbol} Backtest Win Rate: {win_rate_check:.1%} {'≥' if meets_winrate else '<'} {win_rate_threshold:.0%} (threshold)                            │")
            
            print(f"└{'─'*98}┘")
        
        # Safety metrics
        print(f"┌{'─'*98}┐")
        print(f"│ {'SAFETY METRICS':<96} │")
        print(f"├{'─'*98}┤")
        print(f"│ Risk Violations: {risk_violations:>3} | API Errors: {api_errors:>3} | Exchange Rejections: {exchange_rejections:>3} | Circuit Breaker: {'OFF':<6} │")
        print(f"└{'─'*98}┘")
        
        # Alert on first trade
        if trades_executed == 1 and last_event_count > 0:
            print(f"\n✅ FIRST TRADE EXECUTED - Reviewing safety metrics...\n")
        
        # Alert on milestones
        if trades_executed > 0 and trades_executed % 5 == 0:
            print(f"\n📊 MILESTONE: {trades_executed} trades completed")
            print(f"   Win Rate: {win_rate:.1f}% | Total P&L: ${total_profit:+.2f}")
            print(f"   Daily Risk Used: ${daily_risk_used:.2f}/${daily_risk_limit:.2f}")
            print()
        
        # Check for critical issues
        if risk_violations > 0 or exchange_rejections > 3 or api_errors > 5:
            print(f"\n🛑 CRITICAL ISSUES DETECTED")
            print(f"   Risk Violations: {risk_violations}")
            print(f"   Exchange Rejections: {exchange_rejections}")
            print(f"   API Errors: {api_errors}\n")
        
        time.sleep(3)  # Update every 3 seconds

if __name__ == "__main__":
    try:
        monitor_live_detailed()
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
        print("=" * 100)
