"""Render the beginner dedicated-tenancy guide diagrams with Pillow.

Usage: ~/.venv/bin/python dedicated-tenancy-beginner-diagrams.py <output-dir>
"""
import math
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1]
S = 2
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FM = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

INK = (33, 37, 41)
MUTED = (100, 110, 120)
LINE = (90, 98, 108)
# One colour per kind of component
YOU = ((243, 244, 246), (107, 114, 128))     # your workstation, files, browser
MGMT = ((219, 234, 254), (37, 99, 235))      # management cluster: Rancher, Turtles, CAPA
K8S = ((237, 233, 254), (124, 58, 237))      # Kubernetes objects the chart or Turtles creates
AWS = ((254, 243, 199), (217, 119, 6))       # AWS resources
DED = ((220, 252, 231), (22, 163, 74))       # dedicated EC2 instances
OTHER = ((254, 226, 226), (220, 38, 38))     # other AWS customers' instances
WHITE = ((255, 255, 255), (156, 163, 175))   # containers


def font(size, bold=False, mono=False):
    return ImageFont.truetype(FM if mono else (FB if bold else F), size * S)


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.img = Image.new("RGB", (w * S, h * S), "white")
        self.d = ImageDraw.Draw(self.img)

    def text(self, x, y, s, size=14, bold=False, mono=False, fill=INK, anchor="la"):
        self.d.text((x * S, y * S), s, font=font(size, bold, mono), fill=fill, anchor=anchor)

    def width(self, s, size, bold=False, mono=False):
        return font(size, bold, mono).getlength(s) / S

    def box(self, x, y, w, colors, title=None, lines=(), size=13, h=None):
        """Draw a box sized to its content; lines starting with ` are monospace. Returns the bottom y."""
        rows = []
        if title:
            rows.append((title, size + 2, True, False))
        rows += [(ln.lstrip("`"), size, False, ln.startswith("`")) for ln in lines]
        need = 16 + sum(r[1] + 8 for r in rows) + 8
        h = max(h or 0, need)
        for s, sz, b, m in rows:
            tw = self.width(s, sz, b, m)
            assert tw <= w - 16, f"text {s!r} ({tw:.0f}px) does not fit box width {w}"
        fill, border = colors
        self.d.rounded_rectangle([x * S, y * S, (x + w) * S, (y + h) * S], 10 * S,
                                 fill=fill, outline=border, width=2 * S)
        ty = y + 14
        for s, sz, b, m in rows:
            self.text(x + w / 2, ty, s, sz, bold=b, mono=m, anchor="ma")
            ty += sz + 8 + (4 if b else 0)
        return y + h

    def arrow(self, pts, color=LINE, width=2):
        for p, q in zip(pts, pts[1:]):
            self.d.line([(p[0] * S, p[1] * S), (q[0] * S, q[1] * S)], fill=color, width=width * S)
        p, q = pts[-2], pts[-1]
        a = math.atan2(q[1] - p[1], q[0] - p[0])
        tri = [q, (q[0] - 11 * math.cos(a - 0.4), q[1] - 11 * math.sin(a - 0.4)),
               (q[0] - 11 * math.cos(a + 0.4), q[1] - 11 * math.sin(a + 0.4))]
        self.d.polygon([(u * S, v * S) for u, v in tri], fill=color)

    def label(self, x, y, s, size=13, fill=MUTED, anchor="ma", bold=False, mono=False):
        self.text(x, y, s, size, bold=bold, mono=mono, fill=fill, anchor=anchor)

    def title(self, s):
        self.text(self.w / 2, 18, s, 20, bold=True, anchor="ma")

    def save(self, name):
        self.img.resize((self.w, self.h), Image.LANCZOS).save(f"{OUT}/{name}", optimize=True)
        print(name)



def tenancy():
    c = Canvas(1000, 470)
    c.title("Shared tenancy vs Dedicated Instances")
    panels = [(30, YOU, "Shared tenancy (tenancy: default)",
               ["Like an apartment building:", "neighbours share the building"],
               "One physical AWS server",
               [("You", DED), ("Customer B", OTHER), ("Customer C", OTHER)]),
              (520, DED, "Dedicated Instances (tenancy: dedicated)",
               ["Like a house only you live in,", "but you still rent it from AWS"],
               "One physical AWS server, your account only",
               [("You", DED), ("You", DED)])]
    for x, col, t, lines, server, guests in panels:
        c.box(x, 60, 450, col, t, lines, h=330)
        c.box(x + 20, 165, 410, WHITE, server, h=200)
        bw, gap = 118, 14
        x0 = x + 20 + (410 - len(guests) * bw - (len(guests) - 1) * gap) / 2
        for i, (g, gc) in enumerate(guests):
            c.box(x0 + i * (bw + gap), 215, bw, gc, g, ["`EC2", "`instance"])
    c.label(500, 408, "In a VPC with default tenancy, tenancy is set on each EC2 instance.", 14, fill=INK)
    c.label(500, 432, "This guide sets tenancy: dedicated for all three pools: cp, wd and ws.", 14, fill=INK)
    c.save("dedicated-tenancy-beginner-01-shared-vs-dedicated.png")


def big_picture():
    c = Canvas(1000, 640)
    c.title("The big picture: what exists, and what CAPA creates")
    ws_bottom = c.box(20, 60, 300, YOU, "Your workstation",
                      ["AWS CLI checks", "browser for the Rancher UI"])
    # Existing management cluster
    c.box(20, 200, 400, WHITE, "Existing Rancher management cluster",
          ["RKE2 v1.36.4+rke2r1"], h=380)
    c.box(40, 275, 360, MGMT, "Rancher 2.15.2 (Carbide)", ["RKE2 bootstrap and control plane"])
    c.box(40, 365, 360, MGMT, "Rancher Turtles 0.27.2", ["turns the cloud credential into an identity"])
    c.box(40, 455, 360, MGMT, "CAPA v2.11.1 (added in Step 1)", ["creates NLB, security groups, EC2"])
    # AWS
    c.box(540, 60, 440, WHITE, "AWS us-east-1", h=520)
    c.box(560, 100, 400, AWS, "Existing IAM", ["instance profiles, access key"])
    c.box(560, 200, 400, AWS, "Your existing VPC",
          ["existing subnets (public or private)"], h=360)
    c.box(575, 285, 180, DED, "Security groups", ["created by CAPA"])
    c.box(765, 285, 180, DED, "Internal NLB", ["created by CAPA"])
    for x, pool, itype in [(575, "cp", "`m5.large"), (699, "wd", "`m5.large"), (823, "ws", "`t3.medium")]:
        c.box(x, 390, 118, DED, pool, [itype, "dedicated"])
    c.label(760, 500, "3 EC2 Dedicated Instances", 13, fill=INK, bold=True)
    c.label(760, 520, "in your existing subnets", 13, fill=INK)
    # Arrows
    c.arrow([(320, 128), (540, 128)])
    c.label(430, 108, "AWS CLI checks", 12)
    c.arrow([(170, ws_bottom), (170, 200)])
    c.label(182, ws_bottom + 12, "kubectl, helm, access key", 12, anchor="la")
    c.arrow([(400, 300), (560, 300)])
    c.label(480, 282, "RKE2 bootstrap", 12)
    c.arrow([(560, 330), (400, 330)])
    c.label(480, 337, "TCP 443", 12)
    c.arrow([(400, 490), (560, 490)])
    c.label(480, 456, "creates in", 12)
    c.label(480, 472, "your VPC", 12)
    # Legend
    for i, (name, col) in enumerate([("already exists", AWS), ("created by CAPA", DED),
                                     ("management cluster", MGMT)]):
        x = 40 + i * 310
        c.d.rounded_rectangle([x * S, 600 * S, (x + 22) * S, 622 * S], 5 * S,
                              fill=col[0], outline=col[1], width=2 * S)
        c.label(x + 30, 603, name, 13, fill=INK, anchor="la")
    c.save("dedicated-tenancy-beginner-02-big-picture.png")


STEPS = [
    ("Confirm Turtles and Install the CAPA Provider", "admin host", AWS),
    ("Create the AWS Cloud Credential", "admin host", AWS),
    ("Check the Existing VPC", "workstation", AWS),
    ("Write the Cluster Template Chart", "admin host", DED),
    ("Install the Cluster Template", "admin host", DED),
    ("Wait for the Cluster to Become Active", "admin host and browser", DED),
    ("Check That Every Node Is Dedicated", "admin host and workstation", DED),
    ("Delete the Cluster", "admin host and workstation", YOU),
    ("Troubleshoot Common Problems", "where the failing command runs", YOU),
]


def roadmap():
    c = Canvas(1000, 660)
    c.title("Your roadmap: 9 steps")
    bh, gap, top, per_col = 89, 22, 60, 5
    pos = []
    for i, (t, where, col) in enumerate(STEPS):
        x = 40 if i < per_col else 540
        y = top + (i % per_col) * (bh + gap)
        c.box(x, y, 420, col, f"Step {i + 1}", [t, f"Run on: {where}"], h=bh)
        pos.append((x, y))
    for i in range(len(STEPS) - 1):
        (x, y), (nx, ny) = pos[i], pos[i + 1]
        if i == per_col - 1:
            c.arrow([(x + 420, y + bh / 2), (500, y + bh / 2), (500, ny + bh / 2), (nx, ny + bh / 2)])
        else:
            c.arrow([(x + 210, y + bh), (nx + 210, ny)])
    ly = top + per_col * (bh + gap) + 6
    for i, (name, col) in enumerate([("Connect Rancher to AWS", AWS), ("Build the dedicated cluster", DED),
                                     ("Clean up and fix problems", YOU)]):
        x = 40 + i * 310
        c.d.rounded_rectangle([x * S, ly * S, (x + 22) * S, (ly + 22) * S], 5 * S,
                              fill=col[0], outline=col[1], width=2 * S)
        c.label(x + 30, ly + 3, name, 13, fill=INK, anchor="la")
    c.save("dedicated-tenancy-beginner-03-roadmap.png")


def identity():
    c = Canvas(1000, 540)
    c.title("How the cloud credential becomes a CAPA identity")
    c.box(20, 60, 260, YOU, "Existing access key",
          ["access key ID", "secret access key"])
    c.box(340, 60, 260, MGMT, "Rancher 2.15.2", ["Step 2.1: curl POST", "`/v3/cloudcredentials"])
    c_bot = c.box(680, 60, 300, K8S, "Cloud credential Secret",
                  ["`cc-a1b2c in cattle-global-data", "needs the annotation",
                   "`provisioning.cattle.io/driver", "`  = aws"])
    c.arrow([(280, 105), (340, 105)])
    c.arrow([(600, 105), (680, 105)])
    c.label(640, 82, "stores", 12)
    d_top = 260
    c.box(680, d_top, 300, MGMT, "Rancher Turtles 0.27.2",
          ["rancher-credential-translation", "watches annotated Secrets"])
    c.arrow([(830, c_bot), (830, d_top)])
    c.label(840, c_bot + 12, "annotation present", 12, anchor="la")
    e_bot = c.box(340, d_top, 270, K8S, "AWSClusterStaticIdentity",
                  ["`cc-a1b2c", "`allowedNamespaces:", "`  fleet-default", "`secretRef: cc-a1b2c"])
    c.arrow([(680, 300), (610, 300)])
    c.label(645, 278, "creates", 12)
    c.box(20, d_top, 250, K8S, "Secret in capa-system",
          ["`cc-a1b2c", "copy of the keys,", "made by Turtles"])
    c.arrow([(340, 300), (270, 300)])
    c.label(305, 278, "secretRef", 12)
    g_top = e_bot + 50
    c.box(340, g_top, 270, K8S, "AWSCluster capadt",
          ["in fleet-default", "`identityRef: cc-a1b2c"])
    c.arrow([(475, g_top), (475, e_bot)])
    c.label(485, e_bot + 14, "identityRef", 12, anchor="la")
    c.label(660, g_top + 30, "CAPA uses this identity to", 13, fill=INK, anchor="la")
    c.label(660, g_top + 50, "create the AWS resources", 13, fill=INK, anchor="la")
    c.save("dedicated-tenancy-beginner-04-credential-to-identity.png")


def chart():
    c = Canvas(1000, 500)
    c.title("What helm install creates in the management cluster")
    c.box(20, 70, 280, YOU, "capa-dedicated-rke2",
          ["`Chart.yaml", "`values.yaml", "`templates/_helpers.tpl", "`templates/awscluster.yaml",
           "`templates/machinetemplates.yaml", "`templates/cluster.yaml"])
    c.arrow([(300, 170), (400, 170)])
    c.label(350, 150, "helm install", 12)
    c.box(400, 60, 580, WHITE, "Namespace fleet-default", h=420)
    cl_bot = c.box(420, 105, 240, K8S, "Cluster capadt",
                   ["provisioning.cattle.io/v1", "`v1.35.9+rke2r1", "pools cp, wd, ws",
                    "AWS CCM HelmChart 0.0.12"])
    aws_bot = c.box(780, 105, 180, K8S, "AWSCluster capadt",
          ["region us-east-1", "internal NLB", "existing VPC_ID", "2 existing subnets", "(id + cidrBlock)"])
    c.arrow([(660, 150), (780, 150)])
    c.label(720, 128, "infrastructureRef", 12)
    bus = max(cl_bot, aws_bot) + 20
    t_top = bus + 25
    for x, pool, name, itype in [(420, "cp", "`capadt-cp-6214a508", "`m5.large"),
                                 (605, "wd", "`capadt-wd-327e147f", "`m5.large"),
                                 (790, "ws", "`capadt-ws-1d42237e", "`t3.medium")]:
        c.arrow([(540, cl_bot), (540, bus), (x + 85, bus), (x + 85, t_top)])
        t_bot = c.box(x, t_top, 170, K8S, f"{pool} template", [name, itype, "dedicated"])
    c.label(550, cl_bot + 4, "machineConfigRef", 12, anchor="la")
    c.label(690, t_bot + 12, "AWSMachineTemplate name = cluster name + pool name + 8-character hash", 12, fill=INK)
    c.label(690, t_bot + 30, "of ami, sshKeyName, instanceType, iamInstanceProfile and tenancy", 12, fill=INK)
    c.save("dedicated-tenancy-beginner-05-chart-objects.png")


tenancy()
big_picture()
roadmap()
identity()
chart()
