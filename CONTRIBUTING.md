# Contributing to hololinked

First off, thanks for taking the time to contribute!

All types of contributions are encouraged and valued.

> And if you like the project, but just don't have time to contribute, that's fine. There are other easy ways to support the project and show your appreciation, which we would also be very happy about:
>
> - Star the project
> - Tweet about it or share in social media
> - Create examples & refer this project in your project's readme. I can add your example in my [example repository](https://github.com/VigneshVSV/hololinked-examples) if its really helpful, including use cases in more sophisticated integrations
> - Mention the project at local meetups/conferences and tell your friends/colleagues
> - Donate to cover the costs of maintaining it

## I Have a Question

Do feel free to reach out to me at vignesh.vaidyanathan@hololinked.dev or in discord. I will try my very best to respond.

Nevertheless, one may also refer the available how-to section of the [Documentation](https://hololinked.readthedocs.io/en/latest/index.html).
If the documentation is insufficient for any reason including being poorly documented, one may open a new discussion in the [Q&A](https://github.com/VigneshVSV/hololinked/discussions/categories/q-a) section of GitHub discussions.

For questions related to workings of HTTP, JSON schema, basic concepts of python like descriptors, decorators etc., it is also advisable to search the internet for answers first.
For generic questions related to web of things standards or its ideas, it is recommended to join web of things [discord](https://discord.com/invite/RJNYJsEgnb) group and [community](https://www.w3.org/community/wot/) group.

If you believe your question might also be a bug, you might want to search for existing [Issues](https://github.com/VigneshVSV/hololinked/issues) that might help you.
In case you have found a suitable issue and still need clarification, you can write your question in this issue. If an issue is not found:

- Open an [Issue](https://github.com/VigneshVSV/hololinked/issues/new).
- Provide as much context as you can about what you're running into.
  - Stack trace (Traceback)
  - OS, Platform and Version (Windows, Linux, macOS, x86, ARM)
  - Version of python
  - Possibly your input and the output
  - Can you reliably reproduce the issue?

One may submit a bug report at any level of information, especially if you reached out to me at my email upfront. If you also know how to fix it, lets discuss, once the idea is clear, you can fork and make a pull request.

Otherwise, I will then take care of the issue as soon as possible.

> You must never report security related issues, vulnerabilities or bugs including sensitive information to the issue tracker, or elsewhere in public. Instead sensitive bugs must be sent by email to vignesh.vaidyanathan@hololinked.dev.

## I Want To Contribute

> ### Legal Notice <!-- omit in toc -->
>
> When contributing to this project, you must agree that you have authored 100% of the content or that you have the necessary rights to the content. For example, you copied code from projects with MIT/BSD License. Content from GPL-related licenses may be maintained in a separate repository as an add-on.

Developers are always welcome to contribute to the code base. If you want to tackle any issues, un-existing features, let me know (at my email), I can create some open issues and features which I was never able to solve or did not have the time. You can also suggest what else can be contributed functionally, conceptually or also simply code-refactoring.

There are also other repositories which can use your skills:

- An [admin client](https://github.com/VigneshVSV/thing-control-panel) in react
- [Documentation](https://github.com/VigneshVSV/hololinked-docs) in sphinx which needs significant improvement in How-To's, beginner level docs which may teach people concepts of data acquisition or IoT, Docstring or API documentation of this repository itself
- [Examples](https://github.com/VigneshVSV/hololinked-examples) in nodeJS, Dashboard/PyQt GUIs or server implementations using this package. Hardware implementations of unexisting examples are also welcome, I can open a directory where people can search for code based on hardware and just download your code.

## Git Branching

A simpler model is used roughly based on [this article](https://www.bitsnbites.eu/a-stable-mainline-branching-model-for-git/) -

- main branch is where all stable developments are merged, all your branches must merge here
- main branch is merged to release branch when it is decided to created a release.
- A specific release is tagged and not created as its own branch. Instead release branch simply follows the main branch at the release time. People should clone the main branch for latest (mostly-) stable code base and release branch for released code base.
- other branches are feature or bug fix branches. A develop branch may be used to make general improvements as the package is constantly evolving, but its not a specific philosophy to use a develop branch.
- Bug fixes on releases must proceed from the tag of that release. Perhaps, even a new release can be made after fixing the bug by merging a bug fix branch to main branch.

## Attribution

This guide is based on the **contributing-gen**. [Make your own](https://github.com/bttger/contributing-gen)!
