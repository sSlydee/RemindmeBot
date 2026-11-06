# The bot imports its modules from the Bot/ folder ("import lib.Connector"),
# so make Bot/ importable for the tests.
#
# Run all tests from the repository root:
#   python -m unittest discover -s unit_tests -t . -p '*Test.py'
import os
import sys

_BOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Bot')
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)
