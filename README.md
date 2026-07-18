# tech-diagram

[English](README.md) | [日本語](README.ja.md) | [Bahasa Indonesia](README.id.md)

> An Agent Skill that turns a simple JSON grid spec into polished draw.io
> diagrams — AWS / Azure / GCP architecture, ER, UML class diagrams and
> flowcharts. Pure Python stdlib, no external dependencies.

Ask your agent for a diagram; the skill writes a JSON spec that assigns grid
cells (`col`/`row`) to nodes, and the layout engine computes pixel
coordinates, container nesting and sizing, orthogonal routing and label
placement, rendering with each cloud provider's official icons. Every diagram
is then machine-checked for overlaps, piercing, crossings, boundary
correctness and architecture anti-patterns before it reaches you.

[![ECS web app with Multi-AZ redundancy (sample)](docs/images/samples/03-ecs-multiaz.png)](docs/images/samples/03-ecs-multiaz.png)

## Gallery

Everything below is the **unmodified generated output** from the bundled
templates ([templates/](templates/)) and production-grade specs (click for
full size).

### Samples

| | | |
|---|---|---|
| [![ECS Multi-AZ](docs/images/samples/03-ecs-multiaz.png)](docs/images/samples/03-ecs-multiaz.png) | [![Multi-account + TGW](docs/images/samples/04-multiaccount-tgw.png)](docs/images/samples/04-multiaccount-tgw.png) | [![Event-driven reference](docs/images/samples/06-reference-event-driven.png)](docs/images/samples/06-reference-event-driven.png) |
| ECS web app with Multi-AZ redundancy | Multi-account + Transit Gateway | Event-driven reference (numbered badges) |

### 10 templates

| | | |
|---|---|---|
| [![3-tier web](docs/images/templates/example-3tier.png)](docs/images/templates/example-3tier.png) | [![Complex](docs/images/templates/example-complex.png)](docs/images/templates/example-complex.png) | [![Dense 42 nodes](docs/images/templates/example-dense-1page.png)](docs/images/templates/example-dense-1page.png) |
| 3-tier web (`example-3tier`) | Complex system (`example-complex`) | Dense 42 nodes on 1 page (`example-dense-1page`) |
| [![Multi-account](docs/images/templates/example-multiaccount-main.png)](docs/images/templates/example-multiaccount-main.png) | [![Multi-cloud](docs/images/templates/example-multicloud.png)](docs/images/templates/example-multicloud.png) | [![Multi-region DR](docs/images/templates/example-multiregion.png)](docs/images/templates/example-multiregion.png) |
| Multi-account (`example-multiaccount`, [CI/CD tab](docs/images/templates/example-multiaccount-cicd.png)) | Multi-cloud AWS/Azure/GCP (`example-multicloud`) | Multi-region DR (`example-multiregion`) |
| [![Hub & star](docs/images/templates/example-hub-star.png)](docs/images/templates/example-hub-star.png) | [![Reference architecture](docs/images/templates/example-reference.png)](docs/images/templates/example-reference.png) | [![Flowchart](docs/images/templates/example-flowchart.png)](docs/images/templates/example-flowchart.png) |
| High-degree hub & star (`example-hub-star`) | Reference architecture (`example-reference`) | Approval flow with swimlanes (`example-flowchart`) |
| [![ER diagram](docs/images/templates/example-er-uml-er.png)](docs/images/templates/example-er-uml-er.png) | [![UML class diagram](docs/images/templates/example-er-uml-uml.png)](docs/images/templates/example-er-uml-uml.png) | |
| ER diagram (`example-er-uml` tab 1) | UML class diagram (`example-er-uml` tab 2) | |

## Features

- **Diagram types**: AWS / Azure / GCP and multi-cloud architecture diagrams,
  ER diagrams, UML class diagrams, reference architecture diagrams (numbered
  badges + step descriptions), flowcharts (with swimlanes). Sequence diagrams
  are out of scope
- **Routing quality**: shortest-path search on a corridor grid, trying
  multiple routing orders with crossings, congestion and bends as costs, and
  keeping the one with the fewest crossings. Traffic that stays within one
  cloud is kept inside its boundary, and edges never pierce unrelated cloud
  or account boxes
- **Machine validation**: about 20 checks — label overlaps, node piercing,
  edge crossings (a guideline with hub-degree correction), cloud boundary
  conventions (managed services drawn inside subnets, container hierarchy)
  and architecture anti-patterns (see
  [Semantic correctness](#semantic-correctness--diagrams-that-are-architecturally-right))
- **Auto placement**: omit all `col`/`row` for automatic layout; `--optimize`
  runs a deterministic placement local search (`pin` to fix nodes in place)
- **Preview**: `--emit-png` renders a real PNG (auto-detects the draw.io
  CLI); `--emit-svg` emits a self-contained SVG for visual checks without the
  CLI (icons substituted with official-color rectangles)
- **Terraform import**: `tf_to_spec.py` parses `.tf` files directly and
  produces a spec skeleton plus review notes (no credentials, no terraform
  CLI, no state files)
- **Zero dependencies**: Python standard library only (3.10+)

## Semantic correctness — diagrams that are architecturally right

Beyond clean geometry, the skill guards against diagrams that are *drawn
nicely but architecturally wrong*:

- **Pattern catalog** ([references/patterns.md](references/patterns.md)):
  correctness points for standard AWS patterns — 3-tier web (Multi-AZ),
  serverless API, multi-region DR, multi-account, event-driven, static site,
  containers (ECS/Fargate), hybrid — each grounded in AWS primary sources
  (URLs verified 2026-07-18), with an anti-pattern quick-reference table
- **Verified starter specs**
  ([references/reference-architectures/](references/reference-architectures/)):
  5 reference specs (three-tier web, serverless API, multi-region DR, static
  site, ECS containers), all confirmed to build at 0 errors / 0 warnings.
  When your request matches a known pattern, the agent starts from a verified
  spec and edits the diff instead of free-composing
- **Anti-pattern checks (W16–W21)**: placing global edge services
  (CloudFront / Route 53 / WAF) inside a region, VPC or subnet, a database or
  cache in a public subnet, or a direct edge from an external client to a
  database is an **error that rejects the build**; a failover line that
  bypasses CloudFront/WAF straight into the DR load balancer, an
  "HA / Multi-AZ" label with one or zero AZ containers, and a private-subnet
  node reaching outside without NAT / IGW / endpoints are flagged as warnings
- **Calibrated against false positives**: a sweep over 26 real diagrams
  (templates, production-grade specs, flowcharts, reference specs) reports
  zero findings from these checks

## Using it

Place the skill in whatever directory your agent scans for Agent Skills —
any location works, since the skill contains no hardcoded paths. Just name
the folder `tech-diagram` (it is recognized as the skill name).

Then simply ask your agent:

- "Draw an AWS architecture diagram of ..."
- "Draw an ER diagram for these tables"
- "Diagram this approval flow"

The skill activates, builds the diagram, validates it and reports the result.
The full diagramming procedure lives in [SKILL.md](SKILL.md). The generated
`.drawio` files open in the draw.io desktop app, the VS Code extension
(hediet.vscode-drawio), or [app.diagrams.net](https://app.diagrams.net).

### Writing a spec yourself

You can also skip the agent and build from a spec directly:

```bash
python3 scripts/build_drawio.py templates/example-3tier.spec.json -o out.drawio
python3 scripts/find_icon.py --provider azure kubernetes   # search icon names
```

A minimal spec:

```json
{
  "name": "3-tier architecture",
  "meta": {"purpose": "Overview of the web app", "audience": "Dev team",
           "scope": "Production", "abstraction": "Service level"},
  "containers": [
    {"id": "cloud", "label": "AWS Cloud", "type": "aws_cloud"},
    {"id": "vpc", "label": "VPC", "type": "vpc", "parent": "cloud"}
  ],
  "nodes": [
    {"id": "users", "label": "Users", "icon": "users", "col": 0, "row": 0},
    {"id": "alb", "label": "ALB", "icon": "application_load_balancer",
     "col": 1, "row": 0, "parent": "vpc"},
    {"id": "app", "label": "App", "icon": "ec2", "col": 2, "row": 0, "parent": "vpc"}
  ],
  "edges": [
    {"id": "e1", "src": "users", "dst": "alb", "kind": "main", "label": "HTTPS"},
    {"id": "e2", "src": "alb", "dst": "app", "kind": "main"}
  ]
}
```

## Routing quality — Before / After

The router follows the priority principle "looks connected (enters/exits
near edge centers) > straight lines > fewest bends". Same spec, earlier
engine vs. v1.0.0:

| Before (early engine) | After (v1.0.0) |
|---|---|
| [![Vertical line off-center at the endpoints](docs/images/before-after/pairs-anchor-before.png)](docs/images/before-after/pairs-anchor-before.png) | [![Vertical line entering/exiting at edge centers](docs/images/before-after/pairs-anchor-after.png)](docs/images/before-after/pairs-anchor-after.png) |
| Vertical line of a duplicated pair enters/exits off-center (frac 0.65) | Column widening secures the edge center (frac 0.5); a straight line through the icon centers |
| [![Fan with mixed exit and entry sides](docs/images/before-after/fan-mixed-before.png)](docs/images/before-after/fan-mixed-before.png) | [![Fan unified to symmetric slots and mirrored entries](docs/images/before-after/fan-mixed-after.png)](docs/images/before-after/fan-mixed-after.png) |
| Paired edges from the same ALB split between the right and bottom sides, with mixed entry sides | Unified: exits from symmetric right-side slots (0.35/0.65), mirrored entries on facing top/bottom sides |

## Does the skill actually help? (measured)

Whether an agent can go from a natural-language request to a 0-error /
0-warning `.drawio` with no manual fixes, measured with the evaluation suite
in [evals/](evals/) (2026-07-15, n=2 per configuration):

| Configuration | Expectations met | 0-error / 0-warning diagrams |
|---|---|---|
| **With skill** (all 16 evals at the time) | **83/83** | **16/16** |
| Without skill (12 basic evals) | 34/61 | 3/12 |

Grading is done by an independent fresh-context agent that is neither the
eval designer nor the executing agent, and everything machine-checkable is
verified automatically. See [evals/README.md](evals/README.md) for details.

## License and trademarks

- This repository is under the [MIT License](LICENSE). See [NOTICE](NOTICE)
  for attribution of icon metadata derived from draw.io.
- The icon metadata in `references/icons-*.tsv` (names, style strings,
  dimensions) is extracted from the shape libraries of
  [draw.io](https://github.com/jgraph/drawio) (Apache-2.0). **No icon images
  are bundled** — rendering references draw.io's own shape and image
  libraries.
- AWS / Amazon Web Services, Microsoft Azure and Google Cloud names and icons
  are trademarks of their respective owners. Follow each provider's icon
  usage guidelines when using them in diagrams.
