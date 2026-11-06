"""Register the explicit list of built-in command modules."""

from lut.commands import archive, audio, bluetooth, file, image, search, system, video, wifi

# Add built-in modules here; each module exposes register(parser).
MODULES = (search, file, archive, image, video, audio, wifi, bluetooth, system)


def register_commands(parser) -> None:
    """Let each built-in module add its own argparse commands."""
    for module in MODULES:
        module.register(parser)
