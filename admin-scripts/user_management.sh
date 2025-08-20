#!/bin/bash
"""
User Management Script
Automatiza criação, modificação e remoção de usuários em massa
Author: Gabriel Monteiro
"""

set -euo pipefail

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configurações
LOG_FILE="/var/log/user_management.log"
BACKUP_DIR="/var/backups/user_management"
DEFAULT_SHELL="/bin/bash"
DEFAULT_GROUP="users"

# Função de logging
log() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${timestamp} [${level}] ${message}" | tee -a "$LOG_FILE"
}

log_info() { log "INFO" "$@"; }
log_warn() { log "WARN" "${YELLOW}$@${NC}"; }
log_error() { log "ERROR" "${RED}$@${NC}"; }
log_success() { log "SUCCESS" "${GREEN}$@${NC}"; }

# Verificar se é root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Este script deve ser executado como root"
        exit 1
    fi
}

# Backup de arquivos críticos
backup_files() {
    local backup_timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_path="${BACKUP_DIR}/${backup_timestamp}"
    
    mkdir -p "$backup_path"
    
    cp /etc/passwd "${backup_path}/passwd.bak"
    cp /etc/shadow "${backup_path}/shadow.bak"
    cp /etc/group "${backup_path}/group.bak"
    cp /etc/gshadow "${backup_path}/gshadow.bak"
    
    log_info "Backup criado em: $backup_path"
}

# Validar nome de usuário
validate_username() {
    local username=$1
    
    # Verificar formato
    if [[ ! "$username" =~ ^[a-z][-a-z0-9]*$ ]]; then
        log_error "Nome de usuário inválido: $username"
        return 1
    fi
    
    # Verificar tamanho
    if [[ ${#username} -gt 32 ]]; then
        log_error "Nome de usuário muito longo: $username"
        return 1
    fi
    
    return 0
}

# Gerar senha aleatória
generate_password() {
    local length=${1:-12}
    openssl rand -base64 32 | tr -d "=+/" | cut -c1-${length}
}

# Criar usuário
create_user() {
    local username=$1
    local full_name=${2:-""}
    local groups=${3:-"$DEFAULT_GROUP"}
    local shell=${4:-"$DEFAULT_SHELL"}
    local create_home=${5:-"yes"}
    local password=""
    
    # Validar entrada
    if ! validate_username "$username"; then
        return 1
    fi
    
    # Verificar se usuário já existe
    if id "$username" &>/dev/null; then
        log_warn "Usuário $username já existe"
        return 1
    fi
    
    # Gerar senha
    password=$(generate_password 16)
    
    # Criar usuário
    local useradd_opts="-m -s $shell -G $groups"
    if [[ "$create_home" == "no" ]]; then
        useradd_opts="-M -s $shell -G $groups"
    fi
    
    if [[ -n "$full_name" ]]; then
        useradd_opts="$useradd_opts -c \"$full_name\""
    fi
    
    if eval useradd $useradd_opts "$username"; then
        # Definir senha
        echo "$username:$password" | chpasswd
        
        # Forçar mudança de senha no primeiro login
        chage -d 0 "$username"
        
        log_success "Usuário $username criado com sucesso"
        log_info "Senha temporária: $password"
        
        # Salvar credenciais em arquivo seguro
        echo "$username:$password" >> "${BACKUP_DIR}/temp_passwords_$(date +%Y%m%d).txt"
        chmod 600 "${BACKUP_DIR}/temp_passwords_$(date +%Y%m%d).txt"
        
        return 0
    else
        log_error "Falha ao criar usuário $username"
        return 1
    fi
}

# Modificar usuário
modify_user() {
    local username=$1
    local action=$2
    local value=${3:-""}
    
    # Verificar se usuário existe
    if ! id "$username" &>/dev/null; then
        log_error "Usuário $username não existe"
        return 1
    fi
    
    case "$action" in
        "add_group")
            if usermod -a -G "$value" "$username"; then
                log_success "Usuário $username adicionado ao grupo $value"
            else
                log_error "Falha ao adicionar $username ao grupo $value"
                return 1
            fi
            ;;
        "remove_group")
            if gpasswd -d "$username" "$value"; then
                log_success "Usuário $username removido do grupo $value"
            else
                log_error "Falha ao remover $username do grupo $value"
                return 1
            fi
            ;;
        "change_shell")
            if usermod -s "$value" "$username"; then
                log_success "Shell de $username alterado para $value"
            else
                log_error "Falha ao alterar shell de $username"
                return 1
            fi
            ;;
        "lock")
            if usermod -L "$username"; then
                log_success "Usuário $username bloqueado"
            else
                log_error "Falha ao bloquear $username"
                return 1
            fi
            ;;
        "unlock")
            if usermod -U "$username"; then
                log_success "Usuário $username desbloqueado"
            else
                log_error "Falha ao desbloquear $username"
                return 1
            fi
            ;;
        "reset_password")
            local new_password=$(generate_password 16)
            if echo "$username:$new_password" | chpasswd; then
                chage -d 0 "$username"  # Forçar mudança
                log_success "Senha de $username resetada"
                log_info "Nova senha temporária: $new_password"
                echo "$username:$new_password" >> "${BACKUP_DIR}/reset_passwords_$(date +%Y%m%d).txt"
                chmod 600 "${BACKUP_DIR}/reset_passwords_$(date +%Y%m%d).txt"
            else
                log_error "Falha ao resetar senha de $username"
                return 1
            fi
            ;;
        *)
            log_error "Ação inválida: $action"
            return 1
            ;;
    esac
}

# Remover usuário
remove_user() {
    local username=$1
    local remove_home=${2:-"yes"}
    local backup_home=${3:-"yes"}
    
    # Verificar se usuário existe
    if ! id "$username" &>/dev/null; then
        log_error "Usuário $username não existe"
        return 1
    fi
    
    # Backup do home directory se solicitado
    if [[ "$backup_home" == "yes" && -d "/home/$username" ]]; then
        local backup_file="${BACKUP_DIR}/home_${username}_$(date +%Y%m%d_%H%M%S).tar.gz"
        tar -czf "$backup_file" -C /home "$username"
        log_info "Home directory de $username backup em: $backup_file"
    fi
    
    # Remover usuário
    local userdel_opts=""
    if [[ "$remove_home" == "yes" ]]; then
        userdel_opts="-r"
    fi
    
    if userdel $userdel_opts "$username"; then
        log_success "Usuário $username removido com sucesso"
        
        # Matar processos do usuário se ainda estiverem rodando
        pkill -u "$username" 2>/dev/null || true
        
        return 0
    else
        log_error "Falha ao remover usuário $username"
        return 1
    fi
}

# Listar usuários
list_users() {
    local filter=${1:-"all"}
    
    echo -e "\n${BLUE}=== LISTA DE USUÁRIOS ===${NC}"
    printf "%-20s %-15s %-15s %-30s\n" "USERNAME" "UID" "GID" "FULL NAME"
    printf "%-20s %-15s %-15s %-30s\n" "--------" "---" "---" "---------"
    
    while IFS=: read -r username _ uid gid full_name home shell; do
        case "$filter" in
            "system")
                if [[ $uid -lt 1000 ]]; then
                    printf "%-20s %-15s %-15s %-30s\n" "$username" "$uid" "$gid" "$full_name"
                fi
                ;;
            "regular")
                if [[ $uid -ge 1000 && $uid -lt 65534 ]]; then
                    printf "%-20s %-15s %-15s %-30s\n" "$username" "$uid" "$gid" "$full_name"
                fi
                ;;
            "all"|*)
                printf "%-20s %-15s %-15s %-30s\n" "$username" "$uid" "$gid" "$full_name"
                ;;
        esac
    done < /etc/passwd
}

# Criar usuários em massa
bulk_create_users() {
    local csv_file=$1
    
    if [[ ! -f "$csv_file" ]]; then
        log_error "Arquivo não encontrado: $csv_file"
        return 1
    fi
    
    log_info "Iniciando criação em massa de usuários..."
    
    local count=0
    local success=0
    local failed=0
    
    # Ler arquivo CSV (formato: username,full_name,groups,shell)
    while IFS=, read -r username full_name groups shell || [[ -n "$username" ]]; do
        # Pular cabeçalho
        if [[ "$username" == "username" ]]; then
            continue
        fi
        
        # Remover espaços
        username=$(echo "$username" | tr -d ' ')
        full_name=$(echo "$full_name" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        groups=$(echo "$groups" | tr -d ' ')
        shell=$(echo "$shell" | tr -d ' ')
        
        # Usar valores padrão se estiverem vazios
        [[ -z "$groups" ]] && groups="$DEFAULT_GROUP"
        [[ -z "$shell" ]] && shell="$DEFAULT_SHELL"
        
        ((count++))
        
        if create_user "$username" "$full_name" "$groups" "$shell"; then
            ((success++))
        else
            ((failed++))
        fi
        
    done < "$csv_file"
    
    log_info "Criação em massa concluída: $success sucessos, $failed falhas de $count total"
}

# Relatório de usuários
generate_user_report() {
    local output_file=${1:-"/tmp/user_report_$(date +%Y%m%d_%H%M%S).txt"}
    
    {
        echo "RELATÓRIO DE USUÁRIOS - $(date)"
        echo "================================"
        echo
        
        echo "USUÁRIOS REGULARES (UID >= 1000):"
        list_users "regular"
        echo
        
        echo "ÚLTIMOS LOGINS:"
        lastlog | head -20
        echo
        
        echo "USUÁRIOS BLOQUEADOS:"
        passwd -Sa | grep -E "L|NP" | head -10
        echo
        
        echo "GRUPOS E MEMBROS:"
        for group in $(cut -d: -f1 /etc/group | sort); do
            members=$(getent group "$group" | cut -d: -f4)
            if [[ -n "$members" ]]; then
                echo "$group: $members"
            fi
        done
        
    } > "$output_file"
    
    log_success "Relatório gerado: $output_file"
}

# Menu interativo
interactive_menu() {
    while true; do
        echo -e "\n${BLUE}=== GERENCIAMENTO DE USUÁRIOS ===${NC}"
        echo "1. Criar usuário"
        echo "2. Modificar usuário"
        echo "3. Remover usuário"
        echo "4. Listar usuários"
        echo "5. Criação em massa (CSV)"
        echo "6. Gerar relatório"
        echo "7. Sair"
        echo
        read -p "Escolha uma opção: " choice
        
        case $choice in
            1)
                read -p "Nome do usuário: " username
                read -p "Nome completo: " full_name
                read -p "Grupos (separados por vírgula): " groups
                create_user "$username" "$full_name" "$groups"
                ;;
            2)
                read -p "Nome do usuário: " username
                echo "Ações: add_group, remove_group, change_shell, lock, unlock, reset_password"
                read -p "Ação: " action
                read -p "Valor (se necessário): " value
                modify_user "$username" "$action" "$value"
                ;;
            3)
                read -p "Nome do usuário: " username
                read -p "Remover home directory? (yes/no): " remove_home
                read -p "Fazer backup do home? (yes/no): " backup_home
                remove_user "$username" "$remove_home" "$backup_home"
                ;;
            4)
                read -p "Filtro (all/regular/system): " filter
                list_users "$filter"
                ;;
            5)
                read -p "Caminho do arquivo CSV: " csv_file
                bulk_create_users "$csv_file"
                ;;
            6)
                read -p "Arquivo de saída (Enter para padrão): " output_file
                generate_user_report "$output_file"
                ;;
            7)
                log_info "Saindo..."
                break
                ;;
            *)
                log_error "Opção inválida"
                ;;
        esac
    done
}

# Função de ajuda
show_help() {
    cat << EOF
User Management Script - Gabriel Monteiro

USAGE:
    $0 [OPTIONS] COMMAND [ARGS]

COMMANDS:
    create USERNAME [FULL_NAME] [GROUPS] [SHELL]
        Criar novo usuário
        
    modify USERNAME ACTION [VALUE]
        Modificar usuário existente
        Actions: add_group, remove_group, change_shell, lock, unlock, reset_password
        
    remove USERNAME [REMOVE_HOME] [BACKUP_HOME]
        Remover usuário (yes/no para home e backup)
        
    list [FILTER]
        Listar usuários (all/regular/system)
        
    bulk CSV_FILE
        Criar usuários em massa via CSV
        
    report [OUTPUT_FILE]
        Gerar relatório de usuários
        
    interactive
        Menu interativo

OPTIONS:
    -h, --help      Mostrar esta ajuda
    -v, --verbose   Modo verboso
    
EXAMPLES:
    $0 create jdoe "John Doe" "users,developers" "/bin/bash"
    $0 modify jdoe add_group "sudo"
    $0 remove jdoe yes yes
    $0 list regular
    $0 bulk users.csv
    $0 report /tmp/users.txt

CSV FORMAT:
    username,full_name,groups,shell
    jdoe,John Doe,users,/bin/bash
    jsmith,Jane Smith,users:developers,/bin/zsh
EOF
}

# Main
main() {
    # Verificar argumentos
    if [[ $# -eq 0 ]]; then
        interactive_menu
        exit 0
    fi
    
    # Parse argumentos
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_help
                exit 0
                ;;
            -v|--verbose)
                set -x
                shift
                ;;
            create)
                shift
                create_user "$@"
                break
                ;;
            modify)
                shift
                modify_user "$@"
                break
                ;;
            remove)
                shift
                remove_user "$@"
                break
                ;;
            list)
                shift
                list_users "$1"
                break
                ;;
            bulk)
                shift
                bulk_create_users "$1"
                break
                ;;
            report)
                shift
                generate_user_report "$1"
                break
                ;;
            interactive)
                interactive_menu
                break
                ;;
            *)
                log_error "Comando desconhecido: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# Inicialização
check_root
mkdir -p "$BACKUP_DIR"
backup_files

# Executar
main "$@"
