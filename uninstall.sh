#!/bin/bash

# Universal AI Configuration Uninstaller
# Usage:
#   Interactive: curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/uninstall.sh | bash
#   Non-interactive: curl -fsSL https://raw.githubusercontent.com/DevArtsLab/tool-universal-ai-config/main/uninstall.sh | bash -s -- --yes

set -e

# Parse arguments
AUTO_YES=false
REMOVE_CONFIG=false
for arg in "$@"; do
    case $arg in
        --yes|-y)
            AUTO_YES=true
            shift
            ;;
        --remove-config)
            REMOVE_CONFIG=true
            shift
            ;;
        *)
            ;;
    esac
done

# Detect non-interactive environment
if [ -t 0 ]; then
    IS_INTERACTIVE=true
else
    IS_INTERACTIVE=false
fi

if [ "$CI" = "true" ] || [ "$NONINTERACTIVE" = "1" ]; then
    AUTO_YES=true
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

INSTALL_DIR="${HOME}/.universal-ai-config"
BIN_DIR="${HOME}/.local/bin"
SYMLINK="${BIN_DIR}/ai-config"

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

confirm_uninstall() {
    print_warning "This will remove Universal AI Configuration from your system"
    print_warning "Configuration files in ~/.agents/ will be preserved"
    echo ""
    
    if confirm "Are you sure you want to continue?" "N"; then
        return 0
    fi
    
    print_info "Uninstall cancelled"
    exit 0
}

remove_symlink() {
    if [ -L "$SYMLINK" ]; then
        print_info "Removing symlink..."
        rm "$SYMLINK"
        print_success "Removed symlink"
    else
        print_info "Symlink not found (may have been removed manually)"
    fi
}

remove_tool_installs() {
    # Remove uv/pipx managed installs if present
    if command -v uv &> /dev/null && uv tool list 2>/dev/null | grep -q "universal-ai-config"; then
        print_info "Removing uv tool install..."
        uv tool uninstall universal-ai-config
        print_success "Removed uv tool"
    fi
    if command -v pipx &> /dev/null && pipx list --short 2>/dev/null | grep -q "universal-ai-config"; then
        print_info "Removing pipx install..."
        pipx uninstall universal-ai-config
        print_success "Removed pipx install"
    fi
}

remove_installation() {
    if [ -d "$INSTALL_DIR" ]; then
        print_info "Removing installation directory..."
        rm -rf "$INSTALL_DIR"
        print_success "Removed $INSTALL_DIR"
    else
        print_info "Installation directory not found"
    fi
}

ask_remove_config() {
    if [ -d "${HOME}/.agents" ]; then
        print_warning "Configuration files found at ~/.agents/"
        
        if [ "$REMOVE_CONFIG" = true ] || confirm "Do you want to remove configuration files as well?" "N"; then
            print_info "Removing configuration files..."
            rm -rf "${HOME}/.agents"
            print_success "Removed configuration files"
        else
            print_info "Configuration files preserved"
        fi
    fi
}

cleanup_path() {
    print_info "Checking PATH configuration..."
    
    # Detect shell config
    SHELL_CONFIG=""
    if [ -n "$ZSH_VERSION" ]; then
        SHELL_CONFIG="${HOME}/.zshrc"
    elif [ -n "$BASH_VERSION" ]; then
        SHELL_CONFIG="${HOME}/.bashrc"
    fi
    
    if [ -n "$SHELL_CONFIG" ] && [ -f "$SHELL_CONFIG" ]; then
        if grep -q "Universal AI Config" "$SHELL_CONFIG"; then
            print_info "Removing PATH configuration from $SHELL_CONFIG"
            # Remove the lines we added
            sed -i.bak '/# Universal AI Config/,+2d' "$SHELL_CONFIG"
            print_success "Removed PATH configuration"
            print_warning "Please run: source $SHELL_CONFIG"
        fi
    fi
}

main() {
    echo "======================================"
    echo "Universal AI Configuration Uninstaller"
    echo "======================================"
    echo ""
    
    confirm_uninstall
    
    remove_symlink
    remove_tool_installs
    remove_installation
    ask_remove_config
    cleanup_path
    
    echo ""
    print_success "Uninstall complete!"
    echo ""
    print_info "Thank you for using Universal AI Configuration"
}

main
