---
name: explain-with-example
description: Explain a concept or code snippet anchored by a concrete, working example
---
explain with example use tables and flowchart in the explanation.

Note:
1.When generating Mermaid diagrams, always wrap subgraph IDs and node labels containing spaces, dashes, or parentheses in double quotes (e.g., sub_id["Label Text (Extra)"]) to prevent Mermaid parser errors.
2.The Mermaid parser can crash because of putting quotes (") and an arrow (->) inside the edge label pipes (`|...|) confused the syntax rules; the fix is to keep edge labels plain and move detailed text inside the nodes.