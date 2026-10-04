#!/bin/bash

# Universal AI Configuration Installer
# Usage:
#   Interactive: curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/install.sh | bash
#   Non-interactive: curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/install.sh | bash -s -- --yes

set -e

# Parse arguments
AUTO_YES=false
USE_LOCAL=false
for arg in "$@"; do
    case $arg in
        --yes|-y)
            AUTO_YES=true
            shift
            ;;
        --local)
            USE_LOCAL=true
            shift
            ;;
        *)
            # Unknown option
            ;;
    esac
done

# Detect non-interactive environment (no TTY or CI)
if [ -t 0 ]; then
    IS_INTERACTIVE=true
else
    IS_INTERACTIVE=false
fi

if [ "$CI" = "true" ] || [ "$NONINTERACTIVE" = "1" ]; then
    AUTO_YES=true
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
REPO="DevArtsLab/tool-universal-ai-config"
BRANCH="main"
INSTALL_DIR="${HOME}/.universal-ai-config"
VENV_DIR="${INSTALL_DIR}/venv"

# Functions
print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_info() {
    echo "ℹ $1"
}

confirm() {
    local prompt="$1"
    local default="$2"
    
    if [ "$AUTO_YES" = true ]; then
        return 0
    fi
    
    if [ "$IS_INTERACTIVE" = false ]; then
        # In non-interactive mode without --yes, default to no
        if [ "$default" = "Y" ]; then
            return 0
        else
            return 1
        fi
    fi
    
    read -p "$prompt (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        return 0
    fi
    return 1
}

check_python() {
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        print_info "Please install Python 3.8 or higher"
        exit 1
    fi
    
    # Check Python version
    python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    print_success "Found Python $python_version"
    
    # Check if version is >= 3.8
    if [ "$(printf '%s\n' "3.8" "$python_version" | sort -V | head -n1)" != "3.8" ]; then
        print_error "Python 3.8 or higher is required (found $python_version)"
        exit 1
    fi
}

check_pip() {
    if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
        print_error "pip is not installed"
        print_info "Please install pip"
        exit 1
    fi
    print_success "Found pip"
}

detect_existing_installation() {
    if [ -d "$INSTALL_DIR" ]; then
        print_warning "Existing installation found at $INSTALL_DIR"
        
        # Check whether the existing install actually works
        if [ -x "$VENV_DIR/bin/python3" ] && "$VENV_DIR/bin/python3" -c "import universal_ai_config" 2>/dev/null; then
            if confirm "Do you want to remove it and reinstall?" "N"; then
                print_info "Removing existing installation..."
                rm -rf "$INSTALL_DIR"
            else
                print_info "Keeping existing installation"
                exit 0
            fi
        else
            print_warning "Existing installation appears broken"
            if confirm "Remove it and reinstall?" "Y"; then
                print_info "Removing broken installation..."
                rm -rf "$INSTALL_DIR"
            else
                print_info "Keeping existing installation"
                exit 0
            fi
        fi
    fi
}

create_install_dir() {
    print_info "Creating installation directory..."
    mkdir -p "$INSTALL_DIR"
    print_success "Created $INSTALL_DIR"
}

download_package() {
    local source_dir=""
    
    if [ "$USE_LOCAL" = true ]; then
        print_info "Using local package source..."
        
        # Determine source directory before changing to install dir
        if [ -n "$LOCAL_SOURCE_DIR" ]; then
            source_dir="$(cd "$LOCAL_SOURCE_DIR" && pwd)"
        else
            source_dir="$(pwd)"
        fi
        
        # Make sure source dir exists
        if [ ! -d "$source_dir" ] || [ ! -f "$source_dir/pyproject.toml" ]; then
            print_error "Local source directory does not contain pyproject.toml: $source_dir"
            exit 1
        fi
    fi
    
    cd "$INSTALL_DIR"
    
    if [ "$USE_LOCAL" = true ]; then
        # Make sure we're not copying the install dir into itself
        local install_dir_abs
        install_dir_abs="$(pwd)"
        if [ "$source_dir" = "$install_dir_abs" ]; then
            print_error "Source directory cannot be the same as install directory"
            exit 1
        fi
        
        cp -R "$source_dir"/* .
        print_success "Copied local package"
        return
    fi
    
    print_info "Downloading package from GitHub..."
    
    # Try downloading the package
    if command -v curl &> /dev/null; then
        curl -fsSL "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" -o universal-ai-config.tar.gz
    elif command -v wget &> /dev/null; then
        wget -q "https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz" -O universal-ai-config.tar.gz
    else
        print_error "Neither curl nor wget is available"
        exit 1
    fi
    
    print_success "Downloaded package"
    
    # Extract (top-level dir is "<repo>-<branch>", resolve it dynamically)
    print_info "Extracting package..."
    local extract_dir
    extract_dir=$(tar -tzf universal-ai-config.tar.gz | head -1 | cut -d/ -f1)
    tar -xzf universal-ai-config.tar.gz
    mv "$extract_dir"/* .
    rm -rf "$extract_dir" universal-ai-config.tar.gz
    print_success "Extracted package"
}

install_via_pip() {
    print_info "Installing via pip..."
    
    # Create virtual environment
    print_info "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    
    # Activate virtual environment
    source "$VENV_DIR/bin/activate"
    
    # Upgrade pip
    pip install --upgrade pip
    
    # Install package (editable only for local dev installs, so the
    # installation does not break if the source directory moves)
    if [ "$USE_LOCAL" = true ]; then
        pip install -e .
    else
        pip install .
    fi
    
    print_success "Installed package"
}

install_via_tool() {
    # Prefer uv or pipx: they manage the isolated environment and PATH entry
    # themselves, and install straight from PyPI (with a git fallback).
    if command -v uv &> /dev/null; then
        print_info "Installing via uv..."
        if uv tool install --force universal-ai-config 2>/dev/null \
            || uv tool install --force "git+https://github.com/${REPO}"; then
            print_success "Installed via uv"
            return 0
        fi
        print_warning "uv install failed, trying next method..."
    fi
    
    if command -v pipx &> /dev/null; then
        print_info "Installing via pipx..."
        if pipx install --force universal-ai-config 2>/dev/null \
            || pipx install --force "git+https://github.com/${REPO}.git"; then
            print_success "Installed via pipx"
            return 0
        fi
        print_warning "pipx install failed, falling back to venv..."
    fi
    
    return 1
}

create_symlink() {
    print_info "Creating symlink to ai-config command..."
    
    BIN_DIR="${HOME}/.local/bin"
    mkdir -p "$BIN_DIR"
    
    # Create symlink
    ln -sf "${VENV_DIR}/bin/ai-config" "${BIN_DIR}/ai-config"
    
    # Make executable
    chmod +x "${BIN_DIR}/ai-config"
    
    print_success "Created symlink at ${BIN_DIR}/ai-config"
}

update_path() {
    print_info "Checking PATH configuration..."
    
    # Check if ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":${HOME}/.local/bin:"* ]]; then
        print_warning "~/.local/bin is not in your PATH"
        
        # Detect shell
        SHELL_CONFIG=""
        if [ -n "$ZSH_VERSION" ]; then
            SHELL_CONFIG="${HOME}/.zshrc"
        elif [ -n "$BASH_VERSION" ]; then
            SHELL_CONFIG="${HOME}/.bashrc"
        fi
        
        if [ -n "$SHELL_CONFIG" ]; then
            print_info "Adding to $SHELL_CONFIG"
            echo "" >> "$SHELL_CONFIG"
            echo "# Universal AI Config" >> "$SHELL_CONFIG"
            echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$SHELL_CONFIG"
            print_success "Added to $SHELL_CONFIG"
            print_warning "Please run: source $SHELL_CONFIG"
        else
            print_warning "Please add ~/.local/bin to your PATH manually"
        fi
    else
        print_success "~/.local/bin is already in PATH"
    fi
}

detect_legacy_configs() {
    print_info "Checking for legacy configurations..."
    
    LEGACY_FOUND=0
    
    if [ -d "${HOME}/.config/devin" ]; then
        print_warning "Found Devin config at ~/.config/devin"
        LEGACY_FOUND=1
    fi
    
    if [ -d "${HOME}/.windsurf" ]; then
        print_warning "Found Windsurf config at ~/.windsurf"
        LEGACY_FOUND=1
    fi
    
    if [ -d "${HOME}/.config/claude" ]; then
        print_warning "Found Claude config at ~/.config/claude"
        LEGACY_FOUND=1
    fi
    
    return $LEGACY_FOUND
}

prompt_migration() {
    if detect_legacy_configs; then
        echo ""
        print_warning "Legacy configurations detected"
        
        if confirm "Do you want to migrate them to the new unified config?" "N"; then
            return 0
        fi
    fi
    return 1
}

run_ai_config() {
    # Run ai-config regardless of how it was installed (venv, uv, or pipx)
    if [ -f "$VENV_DIR/bin/activate" ]; then
        source "$VENV_DIR/bin/activate"
    fi
    PATH="$HOME/.local/bin:$PATH" ai-config "$@"
}

initialize_config() {
    print_info "Initializing configuration..."
    run_ai_config init
    print_success "Configuration initialized"
}

migrate_configs() {
    print_info "Migrating legacy configurations..."
    run_ai_config migrate
    print_success "Migration complete"
}

validate_installation() {
    print_info "Validating installation..."
    run_ai_config validate
    print_success "Installation validated"
}

show_status() {
    print_info "Installation status:"
    run_ai_config status
}

cleanup() {
    print_info "Cleaning up..."
    # No cleanup needed for now
}

main() {
    echo "======================================"
    echo "Universal AI Configuration Installer"
    echo "======================================"
    echo ""
    
    if [ "$USE_LOCAL" = true ]; then
        # Dev install from local source: venv + editable install
        check_python
        check_pip
        detect_existing_installation
        create_install_dir
        download_package
        install_via_pip
        create_symlink
    elif install_via_tool; then
        # Installed via uv or pipx: they manage env and PATH themselves
        :
    else
        # Fallback: download source and install into a managed venv
        check_python
        check_pip
        detect_existing_installation
        create_install_dir
        download_package
        install_via_pip
        create_symlink
    fi
    
    # Update PATH
    update_path
    
    echo ""
    print_success "Installation complete!"
    echo ""
    
    # Always initialize a fresh config first
    initialize_config
    
    # Check for legacy configs and migrate if present
    if prompt_migration; then
        migrate_configs
    fi
    
    # Validate
    validate_installation
    
    echo ""
    print_success "All done!"
    echo ""
    print_info "You can now use: ai-config"
    print_info "Run 'ai-config --help' for available commands"
    echo ""
    
    # Show status
    show_status
    
    cleanup
}

# Run main function
main
