import os

# Tests stream matches at high speed; skip the 20-second pre-match build-up.
os.environ.setdefault("SECONDSCREEN_INTRO_HOLD", "0")
