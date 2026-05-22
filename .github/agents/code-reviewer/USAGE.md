# Usage Examples - Code Reviewer Agent

## Example 1: Review a Python File

**You ask:**
```
@agent code-reviewer Review this ETL transformation for best practices and PEP8 compliance:

[paste code here]
```

**You get back:**
- ✅ Line-by-line review against checklist
- 🚩 Critical issues (data leakage, hardcoded values, missing error handling)
- ⚠️ Major issues (missing docstrings, wrong patterns)
- 💡 Suggestions for improvement
- Reference to project standards

---

## Example 2: Review a PR Description

**You ask:**
```
@agent code-reviewer Review this code snippet from our training pipeline. 
Check for data leakage, proper logging, and compliance with our standards.

[code snippet]
```

**Expected feedback:**
- Temporal split validation ✓
- Logger usage ✓
- Type hints ✓
- Error handling ✓
- Docstring format ✓

---

## Example 3: Validate Test Coverage

**You ask:**
```
@agent code-reviewer I have a new module at inference/predict.py. 
Are the tests in inference/test_predict.py adequate? 
Check against our smoke test and coverage standards.

Test file: [paste test code]
Module being tested: [paste module code]
```

**Expected feedback:**
- Test pattern validation (fixtures, mocking, assertions)
- Coverage analysis
- Missing test cases
- Recommendations for edge cases

---

## Example 4: Architecture Review

**You ask:**
```
@agent code-reviewer Review if this new module follows our architecture standards:
- Is it in the right directory?
- Does it import from the right places?
- Is it properly modularized?

Module code: [paste]
```

**Expected feedback:**
- ✅ Module location appropriate
- ✅ Imports follow pattern
- ⚠️ Function too long - should be split
- 💡 Suggestion for better abstraction

---

## Example 5: Streamlit App Review

**You ask:**
```
@agent code-reviewer Review this Streamlit page for our standards.
Check separation of concerns, caching, error handling, and language use.

Code: [app/pages/forecast.py content]
```

**Expected feedback:**
- ✅ Proper use of render() pattern
- ✅ Cache TTL appropriate
- ⚠️ Logger call missing after cache hit
- 🚩 Stack trace shown to user (should use st.error with friendly message)

---

## Tips for Best Results

1. **Provide Context:** Tell the agent what the code does (ETL, ML training, UI, etc.)
2. **Specify Scope:** Ask for specific checks (e.g., "focus on data leakage" or "check logging")
3. **Include Related Code:** Show imports and dependencies so agent understands the context
4. **Ask for Examples:** Request refactored code examples, not just criticism
5. **Reference Standards:** Mention AirSense MX standards document if needed

---

## What the Agent Won't Do

- 🚫 Automatically fix code (use code generation agent for that)
- 🚫 Run linters or tests (use terminal tools for that)
- 🚫 Make architectural decisions (that's for human discussion)
- 🚫 Review non-Python code (it's Python-focused)
- 🚫 Approve PRs (it advises, humans decide)

---

## Integration with Workflow

**Typical code review flow:**

1. Developer writes code locally
2. Developer asks: `@agent code-reviewer Review this before I push`
3. Agent provides feedback
4. Developer fixes issues based on feedback
5. Developer pushes to GitHub
6. CI/CD runs Ruff, pytest, type checkers
7. Human code review (armed with agent's findings)
8. Merge to main

---
