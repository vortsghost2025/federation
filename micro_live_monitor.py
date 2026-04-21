#!/usr/bin/env python3
"""
Micro-Live Trading Monitor
Tracks $100 micro-live test with enhanced safety monitoring
"""
import time
import json
from datetime import datetime, timedelta
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

def monitor_micro_live():
    """Monitor micro-live trading session with real-time stats"""
    print("=" * 80)
    print("🔴 MICRO-LIVE TRADING MONITOR - $100 CAPITAL - SOL/USDT ONLY")
    print("=" * 80)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Max Risk Per Trade: $1.00 (1% of $100)")
    print("Target Pairs: SOL/USDT")
    print("Duration: NO TIME CAP - Run until perfect behavior")
    print("=" * 80)
    print()
    
    start_time = time.time()
    initial_balance = 100.0
    current_balance = initial_balance
    
    trades_executed = 0
    wins = 0
    losses = 0
    total_profit = 0.0
    
    risk_violations = 0
    api_errors = 0
    exchange_rejections = 0
    
    last_event_count = 0
    
    while True:
        elapsed = time.time() - start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        
        # Read new events
        events = read_events()
        new_events = events[last_event_count:]
        last_event_count = len(events)
        
        # Process new events
        for event in new_events:
            event_type = event.get('event_type', '')
            
            if event_type == 'trade_executed':
                trades_executed += 1
                profit = event.get('data', {}).get('profit', 0)
                total_profit += profit
                current_balance += profit
                
                if profit > 0:
                    wins += 1
                else:
                    losses += 1
            
            elif event_type == 'risk_violation':
                risk_violations += 1
                print(f"\n⚠️ RISK VIOLATION DETECTED: {event.get('data', {})}\n")
            
            elif event_type == 'api_error':
                api_errors += 1
                print(f"\n❌ API ERROR: {event.get('data', {})}\n")
            
            elif event_type == 'order_rejected':
                exchange_rejections += 1
                print(f"\n❌ EXCHANGE REJECTION: {event.get('data', {})}\n")
        
        # Calculate stats
        win_rate = (wins / trades_executed * 100) if trades_executed > 0 else 0
        profit_pct = ((current_balance - initial_balance) / initial_balance * 100)
        
        # Display dashboard
        print(f"\r⏱️  {hours:02d}:{minutes:02d}:{seconds:02d} | "
              f"Trades: {trades_executed} | "
              f"Win: {win_rate:.1f}% ({wins}W/{losses}L) | "
              f"P&L: ${total_profit:+.2f} ({profit_pct:+.2f}%) | "
              f"Balance: ${current_balance:.2f} | "
              f"Violations: {risk_violations} | "
              f"Errors: {api_errors} | "
              f"Rejects: {exchange_rejections}", 
              end='', flush=True)
        
        # Alert on first trade
        if trades_executed == 1 and last_event_count > 0:
            print(f"\n\n✅ FIRST TRADE EXECUTED - Reviewing safety metrics...\n")
        
        # Alert on every 10 trades
        if trades_executed > 0 and trades_executed % 10 == 0:
            print(f"\n\n📊 MILESTONE: {trades_executed} trades completed\n")
            print(f"   Win Rate: {win_rate:.1f}%")
            print(f"   Total P&L: ${total_profit:+.2f}")
            print(f"   Violations: {risk_violations}")
            print(f"   Errors: {api_errors}")
            print(f"   Rejections: {exchange_rejections}\n")
        
        # Check for critical issues
        if risk_violations > 0 or exchange_rejections > 3 or api_errors > 5:
            print(f"\n\n🛑 CRITICAL ISSUES DETECTED - REVIEW REQUIRED\n")
            print(f"   Risk Violations: {risk_violations}")
            print(f"   Exchange Rejections: {exchange_rejections}")
            print(f"   API Errors: {api_errors}\n")
        
        time.sleep(2)  # Update every 2 seconds

if __name__ == "__main__":
    try:
        monitor_micro_live()
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoring stopped by user")
        print("=" * 80)
