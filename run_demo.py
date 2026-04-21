#!/usr/bin/env python3
"""
Non-interactive demo script for Federation game.
It starts a new game, prints the status, executes a single turn, and prints the status again.
This allows running the game in environments without a tty (e.g., automated tests).
"""

def main():
    from federation_game_console import FederationConsole
    console = FederationConsole()
    console.initialize_game()
    # Initial status
    console.cmd_status()
    # Execute one turn
    console.cmd_turn()
    # Status after turn
    console.cmd_status()

if __name__ == "__main__":
    main()
