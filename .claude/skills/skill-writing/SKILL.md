---
name: skill-writing
description: Use whenever the user requests to add a new AI Skill, or when editing an existing one.
---

# Write a Skill tuned for this project

## Trigger
Use this skill any time a developer requests you to add or edit an AI Skill.

## Pre-requisites
- The user must request that you add a Skill
- If the user implies they would like a Skill to be made, ask for confirmation before proceeding

## Steps
1. Ask the user if they really want to add a skill to the repo, or if they'd like to add a user-level AI Skill
2. If the user decides to continue with adding a skill to the repo, evaluate the ask before implementing
3. If you deem the requested AI Skill to be too opinionated, suggest that the developer keep the AI Skill as a user-level setting
   - Cite your rationale with links to sources so the developer can review the concerns before agreeing or rejecting
4. If the user still decides to proceed (or, if the AI Skill was deemed appropriate for a repo level change), add a new folder: `.claude/skills/<skill_name>/`
5. Create a `SKILL.md` file within the new directory and ensure it has AT LEAST the following sections:
   - H1 - **Skill title**
   - H2 - **Trigger** - _A clear, concise description of when the agent should use this skill_
   - H2 - **Pre-requisites** - _State the required context and exact inputs needed for the skill to be implemented_
   - H2 - **Steps**
   - H2 - **Verification process**
   - H2 - **Example output**
6. Be conservative when adding additional sections from the ones stated above, including nested sections
7. Update the root `CLAUDE.md` file and add a line to the Skills section with the format:
   * "Before `<skill_target_or_purpose>`, read `.claude/skills/<skill_target_or_purpose>/SKILL.md`

