import builtins
import io
import sys
import pytest
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from federation_game_console import FederationConsole

@pytest.fixture
def console():
    console = FederationConsole()
    console.initialize_game()
    return console

def test_initial_status(capsys, console):
    console.cmd_status()
    captured = capsys.readouterr()
    assert "FEDERATION STATUS" in captured.out
    assert "Health" in captured.out

def test_turn_execution(capsys, console):
    console.cmd_turn()
    captured = capsys.readouterr()
    # Should indicate turn execution and narrative
    assert "Executing turn" in captured.out
    assert "Turn complete" in captured.out
    # Turn number should have incremented to 1
    assert console.turn_number == 1

def test_event_flow(capsys, console, monkeypatch):
    # Trigger event, capture the printed event display
    event = console.trigger_event()
    # Simulate user choice by picking first option key
    first_choice = next(iter(event.options))
    # Resolve event
    outcome, impact = console.resolve_event(first_choice)
    # Apply impact manually to check no errors
    console._update_consciousness(impact)
    # Ensure outcome is a string and impact dict
    assert isinstance(outcome, str)
    assert isinstance(impact, dict)

def test_save_and_load(tmp_path):
    # Initialize a fresh console
    console = FederationConsole()
    console.initialize_game()
    # Use a temporary save directory
    save_dir = tmp_path / "saves"
    console.persistence = console.persistence.__class__(str(save_dir))
    # Directly save game data without prompting for filename
    game_data = {
        'turn_number': console.turn_number,
        'game_phase': console.game_phase,
        'consciousness': console.consciousness.__dict__,
        'rivals': [r.__dict__ for r in console.rivals],
        'events_log': console.events_log,
        'turn_history': console.turn_history,
    }
    filepath = console.persistence.save_game(game_data, "test_save.json")
    saved_files = console.persistence.list_saves()
    assert len(saved_files) == 1
    # Load the game back
    loaded_data = console.persistence.load_game(saved_files[0])
    # Verify that loaded data matches what was saved (turn number)
    assert loaded_data['turn_number'] == console.turn_number

