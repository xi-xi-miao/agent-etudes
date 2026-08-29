# References

The design of this repository — the four annotation layers, the retrospective workflow, the
wildcard governance rule, the earliest-cause rule — is borrowed rather than invented. These are the
sources, with what each one contributes.

- **Mozannar, Bansal, Fourney, Horvitz — *Reading Between the Lines: Modeling User Behavior and
  Costs in AI-Assisted Programming* (CHI 2024).**
  <https://dl.acm.org/doi/10.1145/3613904.3641936>
  The CUPS taxonomy: a fixed vocabulary of states, retrospective self-labeling of recorded sessions,
  and timeline / state-machine visualizations of the result. This is the methodological template for
  our whole annotation workflow — including the ASCII phase timeline in `scripts/stats.py` and the
  idea that participants label their *own* sessions afterwards rather than being observed live.

- **Barke, James, Polikarpova — *Grounded Copilot: How Programmers Interact with Code-Generating
  Models* (OOPSLA 2023).**
  <https://dl.acm.org/doi/10.1145/3586030>
  The acceleration / exploration bimodality: programmers are either speeding up work they already
  know how to do, or searching for a shape they do not have yet. Source of our optional stance
  marker (`Build>` for acceleration, `Build~` for exploration) in TAXONOMY.md § 6.

- ***Model or Harness? An Interaction-Centric Taxonomy for Localizing Agent Failures* (arXiv
  2607.28802).**
  <https://arxiv.org/html/2607.28802>
  Failure localization: the observable symptom is usually far downstream of the move that made the
  failure unavoidable. Source of the **earliest-cause rule** for placing `?` and `??` glyphs, and of
  the model-versus-harness distinction that makes `session.yaml`'s `harness:` block worth filling in.

- ***Code with Me or for Me? How Increasing AI Automation Transforms Developer Workflows*
  (CHI 2026).**
  <https://dl.acm.org/doi/10.1145/3772318.3790850>
  A controlled study of developer–agent interaction across levels of automation. Background for the
  Delegate family of moves (`DISPATCH`, `PAIR`, `FORK`, `REVIEW`) — how far you hand off, and what
  it costs you, is exactly the axis this lab is trying to observe.

- ***Are We All Using Agents the Same Way?* (arXiv 2601.20106).**
  <https://arxiv.org/html/2601.20106>
  Evidence that interaction patterns vary systematically with developer experience. This is the
  motivation for comparing people at all: if everyone used agents the same way, reading each other's
  annotated sessions would teach nothing.

- **SpecStory documentation.**
  <https://docs.specstory.com/>
  Git-friendly markdown capture of agent sessions across tools, with secret redaction. The
  recommended (optional) transcript recorder — see `session.yaml`'s `transcript:` block and the
  secret self-review step in CONTRIBUTING.md.

- **The PGN standard and its Numeric Annotation Glyphs.**
  <https://en.wikipedia.org/wiki/Portable_Game_Notation>
  Precedent for a small, standardized, machine-readable set of evaluation marks attached to moves —
  and for the discipline of keeping the mark set fixed so that two annotators mean the same thing.
  Our six glyphs (`!!` `!` `!?` `?!` `?` `??`) are the chess subset, unchanged.

- **Chess annotation practice in general** — game phases (opening / middlegame / endgame),
  evaluation glyphs, and the shared motif vocabulary (fork, pin, zugzwang) that lets two players
  discuss a position in a sentence.
  The structural model for all four of our layers: phases, moves, glyphs, motifs. The reason a
  motif vocabulary is worth the effort is that naming a recurring situation (`doom-loop`,
  `false-summit`, `context-rot`) makes it recognizable the next time it happens to you. The
  reliability check in TAXONOMY.md § 7 is the standard practice of dialogue-act annotation
  research applied to the same idea: two people annotate one session independently,
  `scripts/compare_annotations.py` lists where they disagree, and systematic disagreement about a
  move's meaning triggers a definition-clarification PR rather than an argument.
