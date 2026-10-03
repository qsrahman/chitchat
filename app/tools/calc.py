"""calculator: exact arithmetic."""
import ast
import math
import operator

from app.config import Settings
from app.tools.base import Tool, ToolError, ToolResult

# Arithmetic the model can't be trusted to do in its head. The expression is parsed with `ast` and only numbers,
# the operators below and the listed functions are evaluated, so nothing can reach the interpreter; results are
# bounded so that "9**9**9" is an error and not a hung server.
_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
              ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
_FUNCTIONS = {
    **{n: getattr(math, n) for n in ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "log", "log10",
                                      "log2", "exp", "floor", "ceil", "gcd", "hypot", "radians", "degrees",
                                      "factorial", "comb", "perm")},
    "abs": abs, "round": round, "min": min, "max": max,
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
_COMBINATORIC = {"factorial", "comb", "perm"}
MAX_BITS = 10_000  # of an integer result: about 3,000 digits
MAX_EXPRESSION = 500


def _checked(value):
    if isinstance(value, complex):
        raise ToolError("The result is not a real number.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ToolError("The result is too large or undefined.")
    if isinstance(value, int) and value.bit_length() > MAX_BITS:
        raise ToolError("The result is too large.")
    return value


def _power(base, exponent):
    whole = isinstance(base, int) and isinstance(exponent, int) and exponent > 0
    if whole and abs(base).bit_length() * exponent > MAX_BITS:
        raise ToolError("The result is too large.")
    return base**exponent


def _evaluate(node) -> float:
    match node:
        case ast.Expression(body=body):
            return _evaluate(body)
        case ast.Constant(value=int() | float() as value) if type(value) is not bool:
            return value
        case ast.Name(id=name) if name in _CONSTANTS:
            return _CONSTANTS[name]
        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_evaluate(operand)
        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _evaluate(operand)
        case ast.BinOp(left=left, op=ast.Pow(), right=right):
            return _checked(_power(_evaluate(left), _evaluate(right)))
        case ast.BinOp(left=left, op=op, right=right) if type(op) in _OPERATORS:
            return _checked(_OPERATORS[type(op)](_evaluate(left), _evaluate(right)))
        case ast.Call(func=ast.Name(id=name), args=args, keywords=[]) if name in _FUNCTIONS:
            values = [_evaluate(a) for a in args]
            if name in _COMBINATORIC and any(not isinstance(v, int) or abs(v) > 1000 for v in values):
                raise ToolError(f"{name} takes whole numbers up to 1000.")
            return _checked(_FUNCTIONS[name](*values))
    raise ToolError(
        "Unsupported expression. Use numbers, + - * / // % **, parentheses, pi, e, tau and the listed functions "
        "(write powers as **, not ^)."
    )


async def calculator(args: dict) -> ToolResult:
    expression = str(args.get("expression") or "").strip()
    if not expression:
        raise ToolError("The expression was empty.")
    if len(expression) > MAX_EXPRESSION:
        raise ToolError("The expression is too long.")
    try:
        value = _evaluate(ast.parse(expression, mode="eval"))
    except SyntaxError as e:
        raise ToolError("The expression could not be parsed.") from e
    except ZeroDivisionError as e:
        raise ToolError("Division by zero.") from e
    except (ValueError, TypeError, OverflowError) as e:
        raise ToolError(f"The expression could not be evaluated ({e}).") from e
    except (RecursionError, MemoryError) as e:
        raise ToolError("The expression is too complex.") from e
    result = str(value) if isinstance(value, int) else f"{value:.15g}"
    return ToolResult(f"{expression} = {result}", {"expression": expression, "result": result})


def make(settings: Settings) -> Tool:
    return Tool(
        name="calculator",
        label="Calculator",
        hint="Exact arithmetic instead of mental maths",
        description=(
            "Evaluate one arithmetic expression exactly. Supports + - * / // % ** and parentheses, the constants "
            "pi, e and tau, and the functions sqrt, sin, cos, tan, asin, acos, atan, atan2, log, log10, log2, exp, "
            "abs, round, floor, ceil, min, max, gcd, hypot, radians, degrees, factorial, comb and perm. "
            "Write powers with **, not ^."
        ),
        parameters={
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "For example: (1.07 ** 10) * 2500"}},
            "required": ["expression"],
            "additionalProperties": False,
        },
        run=calculator,
        guidance=(
            "Use the calculator tool for arithmetic that is more than trivial (several digits, percentages, "
            "compound interest, unit conversions) instead of working it out yourself, and report its result."
        ),
    )
