{ pkgs, lib, config, inputs, ... }:

{
  # Python language configuration with uv
  languages.python = {
    enable = true;
    version = "3.11";
    uv = {
      enable = true;
      sync.enable = true;
      sync.allExtras = true;
    };
  };

  # CLI Packages
  packages = with pkgs; [
    git
    uv
    ruff
  ];

  # Automated Git pre-commit hooks
  pre-commit.hooks = {
    ruff.enable = true;
    ruff-format.enable = true;
  };

  # Shell initialization banner
  enterShell = ''
    echo "🚀 cf-docker-tunnel-sync development environment loaded!"
    echo "Commands:"
    echo "  uv run pytest      - Run hermetic test suite"
    echo "  uv run ruff check  - Run code linter"
    echo "  uv run ruff format - Format code"
  '';
}
