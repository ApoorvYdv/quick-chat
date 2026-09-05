import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

ALEMBIC_PATHS = {
    "config": BASE_DIR / "config" / "alembic.ini",
    "agency": BASE_DIR / "agency" / "alembic.ini",
}

MIGRATION_ORDER = ["config", "agency"]


def run_command(cmd):
    print(f"\nRUNNING: {' '.join(cmd)}\n")

    # Let alembic print everything directly
    result = subprocess.run(cmd)

    # Exit with same exit code if command fails
    if result.returncode != 0:
        print(f"\n Command failed with exit code {result.returncode}\n")
        sys.exit(result.returncode)


def run_alembic(
    migration_type, command, message=None, autogenerate=False, revision="head"
):
    alembic_ini = ALEMBIC_PATHS[migration_type]

    base_cmd = ["alembic", "-c", str(alembic_ini)]

    if command == "revision":
        cmd = base_cmd + ["revision"]

        if autogenerate:
            cmd.append("--autogenerate")

        if message:
            cmd += ["-m", message]

    elif command == "upgrade":
        cmd = base_cmd + ["upgrade", revision]

    elif command == "downgrade":
        cmd = base_cmd + ["downgrade", revision]

    else:
        print("Invalid command. Use revision | upgrade | downgrade")
        sys.exit(1)

    run_command(cmd)


def run_all(command, message=None, autogenerate=False, revision="head"):
    """Run migrations in dependency order"""

    if command == "downgrade":
        order = reversed(MIGRATION_ORDER)
    else:
        order = MIGRATION_ORDER

    for migration_type in order:
        run_alembic(
            migration_type,
            command,
            message=message,
            autogenerate=autogenerate,
            revision=revision,
        )


def main():
    parser = argparse.ArgumentParser(description="Run Alembic migrations")

    parser.add_argument(
        "command",
        choices=["revision", "upgrade", "downgrade"],
        help="Alembic command",
    )

    parser.add_argument(
        "-t",
        "--target",
        choices=["config", "agency", "all"],
        default="all",
        help="Which migration to run",
    )

    parser.add_argument(
        "-m",
        "--message",
        help="Revision message",
    )

    parser.add_argument(
        "--autogenerate",
        action="store_true",
        help="Enable autogenerate",
    )

    parser.add_argument(
        "-r",
        "--revision",
        default="head",
        help="Revision target (default=head, downgrade example: -1)",
    )

    args = parser.parse_args()

    if args.target == "all":
        run_all(
            command=args.command,
            message=args.message,
            autogenerate=args.autogenerate,
            revision=args.revision,
        )
    else:
        run_alembic(
            args.target,
            args.command,
            message=args.message,
            autogenerate=args.autogenerate,
            revision=args.revision,
        )


if __name__ == "__main__":
    main()