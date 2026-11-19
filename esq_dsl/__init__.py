"""Synth: typed execution-signature program synthesis."""

from .dsl import LAMBDAS, OPS, LAMBDA_FAMILY
from .interpreter import execute_program, parse_program
from .synthesizer import synthesize_priority

__version__ = "1.0.0"
