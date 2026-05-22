# AirSense MX Copilot Agents

Custom VS Code Copilot agents for specialized development tasks. Each agent is a specialized version of Claude with domain expertise for your project.

## Directory Structure

```
.github/agents/
├── README.md                    # This file
├── code-reviewer/              # Code quality and standards review
│   ├── AGENT.md               # Agent instructions and rules
│   └── USAGE.md               # Examples and usage guide
├── data-engineer/             # [Future] ETL design and optimization
├── ml-engineer/               # [Future] Model development and evaluation
└── devops/                    # [Future] Infrastructure and deployment
```

## Available Agents

### 1. Code Reviewer
**Purpose:** Validate Python code against PEP8, best practices, and AirSense MX standards.

**When to use:** Before pushing code, to catch issues with style, architecture, testing, and compliance.

**Ask it to:**
- Review code snippets or files
- Check PEP8 and type hint compliance
- Validate architectural patterns (ETL, ML pipelines, Streamlit)
- Verify test coverage and patterns
- Audit logging and error handling
- Check database schema and loaders

**Run it:**
```
@agent code-reviewer Review this function for PEP8 and best practices:
[your code]
```

**Reference:** See [code-reviewer/AGENT.md](code-reviewer/AGENT.md) and [code-reviewer/USAGE.md](code-reviewer/USAGE.md)

---

## Creating New Agents

To create a new agent:

1. **Create directory:** `.github/agents/{agent-name}/`
2. **Create AGENT.md:** Define the agent's role, rules, and checklist
3. **Create USAGE.md:** Provide examples and when to use it
4. **Document:** Update this README with the new agent

### Agent File Structure

Each agent needs:
- **AGENT.md** — Full instructions, checklist, rules, examples of issues to flag
- **USAGE.md** — Practical examples of how to use the agent
- **Optional:** Config files, templates, or additional reference docs

### AGENT.md Template

```markdown
# [Agent Name] Agent for AirSense MX

**Role:** [One-line description]

**Personality:** [How the agent should communicate]

---

## Core Responsibilities

1. [First responsibility]
2. [Second responsibility]
...

## Review Checklist / Decision Framework

- [ ] Item 1
- [ ] Item 2
...

## Common Issues to Flag

### 🚩 Critical Issues

### ⚠️ Major Issues

### 💡 Minor Issues & Suggestions

## How to Provide Feedback

[Format examples]

## When to Use This Agent

Ask when...
Ask another agent when...

## Reference Links

- Link 1
- Link 2
```

---

## Naming Conventions

- **Agent directories:** `{domain-name}` in `kebab-case` (e.g., `code-reviewer`, `ml-engineer`)
- **AGENT.md:** Always named `AGENT.md` (instructions and rules)
- **USAGE.md:** Always named `USAGE.md` (examples and practical guide)

---

## Integration with Copilot

Agents appear in VS Code when:
1. They're properly structured in `.github/agents/{name}/AGENT.md`
2. You invoke them with `@agent {name}`
3. Copilot recognizes the pattern and routes the request

Example:
```
@agent code-reviewer Review this for PEP8 compliance
@agent ml-engineer Should I use LightGBM or XGBoost?
@agent devops How should I containerize this?
```

---

## Best Practices for Agents

✅ **DO:**
- Make agents **specialized** (one domain per agent)
- Provide **clear checklists** that are easy to follow
- Include **concrete examples** of good and bad patterns
- Reference **project standards** (copilot-instructions.md)
- Update agents when standards change
- Keep instructions **actionable** and **specific**

❌ **DON'T:**
- Create too many overlapping agents
- Make agents too general ("all-purpose reviewer")
- Leave agents without examples
- Forget to link to project documentation
- Make instructions too long (keep focused)

---

## Maintenance

When you update `copilot-instructions.md`:
- ✅ Update relevant agent instructions to match
- ✅ Add new patterns to checklist if applicable
- ✅ Update example issues if standards change

---

## Questions?

Refer to the specific agent's USAGE.md for examples, or update this README to clarify.

---

*Last updated: May 22, 2026*
