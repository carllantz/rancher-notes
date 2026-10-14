# rancher-notes

Personal notes and worked examples from my own experiments with [Rancher](https://www.rancher.com/) and RKE2.

Most of these are step-by-step guides written as I built things in my own lab. Each one lists the versions it was tested on, the variables you need to fill in, and a verification checklist after every step, so you can tell where something went wrong.

> **Disclaimer:** This is a personal repo. It is not affiliated with or endorsed by SUSE or Rancher, and nothing here is official documentation. The guides create real cloud resources that cost money. Read each step before you run it, and use an account and cluster you can afford to break.

## Youtube Videos
Video guides
https://www.youtube.com/@Carl-Videos

## Guides

| Guide | What it covers |
|---|---|
| [Dedicated Tenancy Rancher Cluster on AWS: A Beginner's Guide](examples/Dedicated_Tenancy_Rancher_Cluster_On_AWS_Beginner_Guide.md) | Building a three-node RKE2 cluster on AWS where every node is an EC2 Dedicated Instance, using Rancher Turtles and CAPA (Cluster API Provider for AWS) with an existing Rancher management cluster, IAM resources and VPC. Covers installing CAPA, creating the cloud credential, writing a cluster template Helm chart, checking tenancy on every instance, and cleaning up afterwards. |


## Repository layout

```
rancher-notes/
├── examples/            # Step-by-step guides
│   └── assets/          # Diagrams for the guides, plus the script that generates them
├── LICENSE
└── README.md
```


## What you will usually need

- A Rancher management cluster you have admin access to
- `kubectl` and `helm` on your workstation, with a kubeconfig for the management cluster

Each guide's **Pre-requisites** section lists exactly what it needs.

## How the guides are written

- **Variables up front.** Every value you need to change (hostnames, IDs, names, regions) is listed in a variables section, written in `UPPER_CASE`. Set them once and the commands work as written.
- **Small numbered steps.** Each step does one thing and ends with a verification checklist.
- **Cleanup included.** Guides that create infrastructure end with a step that deletes it and confirms nothing was left behind.
- **Diagrams are generated.** The images in `examples/assets/` are built from the Python script in the same folder, so they can be regenerated when a guide changes.

## Secrets

No real credentials, tokens, kubeconfigs or account IDs belong in this repo. Commands use placeholder variables instead. If you fork this, check before committing anything from your own environment.

## Useful links

- [Rancher documentation](https://ranchermanager.docs.rancher.com/)

## Contributing

This is mostly for my own reference, but if you spot a mistake or know a better way to do something, issues and pull requests are welcome.

## License

[MIT](LICENSE) © 2026 Carl Lantz
