# Cline Terminal Integration Fix

## Problem Statement

Cline cannot capture command output due to complex bash prompt configuration containing:
- ANSI escape sequences for colors
- Dynamic command substitution `$(parse_git_branch)`
- Complex PROMPT_COMMAND hooks

## Current Configuration

```bash
PS1=\[\]\w \[\033[32m\]$(parse_git_branch)\[\033[00m\]$ \[\]
PROMPT_COMMAND=__bp_precmd_invoke_cmd
_bash_history_sync; :
```

## Solution Options

### Option 1: VSCode-Specific Bash Configuration (Recommended)

Create a simplified prompt when running inside VSCode terminals while keeping your regular terminal prompt unchanged.

**Implementation:**

1. Add to `~/.bashrc`:

```bash
# Detect if running in VSCode terminal
if [ "$TERM_PROGRAM" = "vscode" ]; then
    # Simplified prompt for VSCode/Cline compatibility
    PS1='\w \$ '
    unset PROMPT_COMMAND
else
    # Keep your existing fancy prompt for regular terminals
    PS1='\[\]\w \[\033[32m\]$(parse_git_branch)\[\033[00m\]$ \[\]'
    PROMPT_COMMAND='__bp_precmd_invoke_cmd; _bash_history_sync; :'
fi
```

**Pros:**
- Preserves your custom prompt in regular terminals
- Only affects VSCode terminals
- Minimal configuration changes
- Cline will work perfectly

**Cons:**
- VSCode terminals won't have git branch display

### Option 2: Static Prompt with Git Branch

Use a static git branch display that Cline can parse:

```bash
if [ "$TERM_PROGRAM" = "vscode" ]; then
    # Static git branch (updates only when prompt is displayed)
    parse_git_branch_static() {
        git branch 2>/dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/(\1)/'
    }
    PS1='\w $(parse_git_branch_static)\$ '
    unset PROMPT_COMMAND
fi
```

**Note:** This still uses command substitution but removes ANSI codes and PROMPT_COMMAND.

**Pros:**
- Keeps git branch information
- Should work with Cline

**Cons:**
- No color coding
- Command substitution may still cause occasional issues

### Option 3: Completely Minimal Prompt

Simplest approach - use basic bash prompt:

```bash
if [ "$TERM_PROGRAM" = "vscode" ]; then
    PS1='\$ '
    unset PROMPT_COMMAND
fi
```

**Pros:**
- Guaranteed to work with Cline
- Fastest prompt rendering
- Zero parsing issues

**Cons:**
- No path or git branch information
- Less informative

### Option 4: Create Cline-Specific Init File

Create a dedicated initialization file for Cline sessions:

1. Create `~/.bashrc_cline`:

```bash
# Simplified bash configuration for Cline/VSCode
PS1='\w \$ '
unset PROMPT_COMMAND

# Keep all your functions and aliases
source ~/.bashrc
```

2. Configure VSCode settings (`.vscode/settings.json`):

```json
{
  "terminal.integrated.shell.linux": "/bin/bash",
  "terminal.integrated.shellArgs.linux": ["--init-file", "~/.bashrc_cline"]
}
```

**Pros:**
- Complete control over Cline environment
- Doesn't affect other environments
- Can be project-specific

**Cons:**
- Requires VSCode configuration
- More complex setup

## Recommended Implementation Steps

**I recommend Option 1** as the best balance of functionality and compatibility.

### Step-by-Step Instructions:

1. **Backup your current .bashrc:**
```bash
cp ~/.bashrc ~/.bashrc.backup
```

2. **Edit your ~/.bashrc** and locate your PS1 and PROMPT_COMMAND settings

3. **Replace or wrap them with VSCode detection:**

```bash
# Detect if running in VSCode terminal
if [ "$TERM_PROGRAM" = "vscode" ]; then
    # Simplified prompt for VSCode/Cline compatibility
    PS1='\w \$ '
    unset PROMPT_COMMAND
else
    # Your existing prompt configuration
    PS1='\[\]\w \[\033[32m\]$(parse_git_branch)\[\033[00m\]$ \[\]'
    # Your existing PROMPT_COMMAND if any
fi
```

4. **Keep your parse_git_branch function** (it won't be called in VSCode):

```bash
parse_git_branch() {
    git branch 2> /dev/null | sed -e '/^[^*]/d' -e 's/* \(.*\)/(\1)/'
}
```

5. **Reload your configuration:**
```bash
source ~/.bashrc
```

6. **Open a new terminal in VSCode** and verify:
```bash
echo "PS1=$PS1"  # Should show: \w \$ 
echo $TERM_PROGRAM  # Should show: vscode
```

7. **Test Cline** by running a simple command and verifying output is captured

## Testing Checklist

After implementing the fix:

- [ ] Can Cline capture output from `echo "test"`?
- [ ] Can Cline capture output from `ls`?
- [ ] Can Cline capture output from `npm run lint`?
- [ ] Do long-running commands work properly?
- [ ] Does your regular terminal (outside VSCode) still have the fancy prompt?

## Verification Commands

Run these commands to test Cline's output capture:

```bash
# Simple output
echo "Test output capture"

# Multi-line output
ls -la

# Command with pipe
echo "Line 1" && echo "Line 2" && echo "Line 3"

# Long-running command
sleep 2 && echo "Completed after delay"
```

## Rollback Instructions

If something goes wrong:

```bash
# Restore your original configuration
cp ~/.bashrc.backup ~/.bashrc
source ~/.bashrc
```

## Additional Notes

- The `TERM_PROGRAM` environment variable is set by VSCode
- This approach doesn't affect other terminal emulators
- You can still use your fancy prompt in iTerm2, Terminal.app, etc.
- The simplified prompt only applies to VSCode integrated terminals
