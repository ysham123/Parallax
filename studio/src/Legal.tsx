import { useEffect, type ReactNode } from "react";
import { Mark, PublicFooter, ThemeToggle, applyStoredTheme } from "./PublicChrome";
import { REPOSITORY, type LegalPage } from "./session";
import "./public.css";

const UPDATED = "October 9, 2026";
const CONTACT = "yosefshammout123@gmail.com";
const ISSUES = `${REPOSITORY}/issues`;

const TITLES: Record<LegalPage, string> = {
  privacy: "Privacy policy",
  terms: "Terms of service",
  support: "Support",
};

function Mail() {
  return <a href={`mailto:${CONTACT}`}>{CONTACT}</a>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function Privacy() {
  return (
    <>
      <p>
        Parallax is published by Yosef Shammout. This policy covers the Parallax plugins and
        command line tool (the local software) and the hosted service at this address. It describes
        what each one collects, why, and what you can do about it.
      </p>
      <Section title="The local software">
        <p>
          The Claude Code and Codex plugins and the command line tool run on your computer. Project
          files, working copies, run history, provider sign-ins and API keys stay on your machine.
          Parallax does not receive them.
        </p>
        <ul>
          <li>
            Prompts and the relevant parts of your project go directly from your machine to the AI
            providers you choose (such as OpenAI, Anthropic, xAI or Google), under their terms.
          </li>
          <li>
            On first use, the software downloads pinned, checksum-verified Python packages from
            PyPI.
          </li>
          <li>
            Feedback metrics are opt-in, recorded locally, and leave your machine only if you export
            and send them yourself.
          </li>
        </ul>
      </Section>
      <Section title="What the hosted service collects">
        <ul>
          <li>
            <strong>Account:</strong> your email address, display name, profile picture address, the
            sign-in method you use (email, GitHub or Google), your GitHub account number if you sign
            in with GitHub, and when you created the account and last signed in.
          </li>
          <li>
            <strong>Password:</strong> sent through our server to our authentication provider to
            sign you in. Parallax never stores it.
          </li>
          <li>
            <strong>Sessions:</strong> a cookie keeps you signed in for up to seven days. The server
            stores only a one-way hash of it.
          </li>
          <li>
            <strong>Machines you connect:</strong> each machine&apos;s name, platform, approved project
            folders and when it was last online.
          </li>
          <li>
            <strong>Run evidence:</strong> results, changes, check output and progress events that
            your machines mirror so your workspace can show them, kept within a fixed storage limit
            per machine with the oldest removed first. Your source files stay on your machine.
          </li>
          <li>
            <strong>Abuse protection:</strong> counters keyed by one-way hashes, such as a hash of an
            email address after repeated failed sign-ins, deleted within 24 hours.
          </li>
        </ul>
        <p>
          The service uses only the cookies it needs to keep you signed in and to finish a sign-in
          you started. There is no advertising or analytics tracking. Your theme choice is saved in
          your browser.
        </p>
      </Section>
      <Section title="How it is used">
        <p>
          To provide the service: signing you in, sending account emails such as confirmation and
          password reset links, showing your machines and runs, enforcing limits, and keeping the
          service secure. Your data is not sold, used for advertising, or used to train AI models.
        </p>
      </Section>
      <Section title="Service providers">
        <ul>
          <li>Supabase, for sign-in and account authentication</li>
          <li>Resend, to deliver account emails</li>
          <li>Vercel, to serve this website</li>
          <li>Railway, to host the service and its storage</li>
          <li>GitHub or Google, only if you choose to sign in with them</li>
        </ul>
        <p>
          These providers process data on our behalf and may keep standard request logs, including
          IP addresses. They are based in the United States, so your data may be processed there.
        </p>
      </Section>
      <Section title="Keeping and deleting data">
        <ul>
          <li>Account data is kept until you delete your account.</li>
          <li>
            Requests relayed to your machines are deleted once answered. Unclaimed answers are
            dropped after five minutes and unanswered requests after one day.
          </li>
          <li>
            Disconnecting a machine deletes its mirrored evidence. Deleting your account, from the
            account menu, removes your workspace, machines, pairing codes, mirrored evidence,
            sessions and sign-in record.
          </li>
          <li>
            Backups made for maintenance are kept only as long as needed to recover from a failed
            update.
          </li>
          <li>
            GitHub and Google keep their own record of the authorization until you revoke it in
            your account settings there.
          </li>
        </ul>
      </Section>
      <Section title="Your choices and rights">
        <p>
          You can see your account details in the account menu and delete your account at any time.
          To ask for a copy of your data, a correction, or deletion, email <Mail />.
        </p>
      </Section>
      <Section title="Security">
        <p>
          Traffic is encrypted, sessions are stored as hashes, and each account&apos;s workspace is
          isolated from every other account on the server. No system is perfectly secure; report
          vulnerabilities privately through{" "}
          <a href={`${REPOSITORY}/security/advisories/new`}>GitHub</a>.
        </p>
      </Section>
      <Section title="Children">
        <p>The service is not intended for anyone under 16.</p>
      </Section>
      <Section title="Changes">
        <p>
          Updates to this policy are posted here with a new date. Account holders are emailed about
          material changes.
        </p>
      </Section>
      <Section title="Contact">
        <p>
          Questions about privacy: <Mail />.
        </p>
      </Section>
    </>
  );
}

function Terms() {
  return (
    <>
      <p>
        These terms cover your use of the hosted Parallax service, published by Yosef Shammout. By
        creating an account or using the service, you agree to them. You must be at least 16.
      </p>
      <Section title="The software">
        <p>
          Parallax&apos;s source code is open source under the{" "}
          <a href={`${REPOSITORY}/blob/main/LICENSE`}>MIT license</a>, which governs the code. These
          terms govern the hosted service.
        </p>
      </Section>
      <Section title="Your account">
        <p>
          Give accurate information, keep your sign-in secure, and use one account per person. You
          are responsible for activity under your account.
        </p>
      </Section>
      <Section title="Your code, machines and providers">
        <ul>
          <li>
            You keep ownership of your code and of the evidence your runs produce. You allow the
            service to store and process mirrored evidence only to provide the service to you.
          </li>
          <li>
            You are responsible for the machines you connect, the project folders you approve, and
            following the terms of the AI providers you use.
          </li>
          <li>Only use Parallax on code you have the right to work on.</li>
        </ul>
      </Section>
      <Section title="Acceptable use">
        <p>Do not:</p>
        <ul>
          <li>break the law or infringe anyone&apos;s rights</li>
          <li>try to reach other accounts, get around limits or isolation, or disrupt the service</li>
          <li>use the service to create or spread malware</li>
          <li>resell or share access to the service</li>
        </ul>
      </Section>
      <Section title="AI output">
        <p>
          Changes are written by third-party AI models. Parallax&apos;s independent reviews and project
          checks reduce risk but cannot guarantee correct or secure results. Review what reaches
          your project; you are responsible for the changes you keep.
        </p>
      </Section>
      <Section title="Availability">
        <p>
          The service is free and early. Features, limits and the number of accounts may change, and
          the service may be paused or discontinued. Account holders are given notice before the
          service is discontinued, where possible.
        </p>
      </Section>
      <Section title="Ending your use">
        <p>
          You can delete your account at any time. An account may be suspended or removed for
          breaking these terms or to protect the service or other users.
        </p>
      </Section>
      <Section title="Disclaimer and liability">
        <p>
          The service is provided &ldquo;as is&rdquo;, without warranties of any kind. To the extent
          the law allows, Yosef Shammout is not liable for indirect, incidental or consequential
          damages, or for lost data or profits, arising from your use of the service.
        </p>
      </Section>
      <Section title="Changes">
        <p>
          Updated terms are posted here with a new date. Account holders are emailed about material
          changes, and continued use after that means you accept them.
        </p>
      </Section>
      <Section title="Contact">
        <p>
          Questions about these terms: <Mail />.
        </p>
      </Section>
    </>
  );
}

function Support() {
  return (
    <>
      <p>Parallax is maintained by Yosef Shammout. Here is the fastest way to get help.</p>
      <Section title="Questions and bugs">
        <p>
          Open an issue on <a href={ISSUES}>GitHub</a>. Include the Parallax version, how you run it
          (Claude Code, Codex, the command line or the hosted Studio), and the steps to reproduce.
          Leave out credentials, private prompts and project contents.
        </p>
      </Section>
      <Section title="Your account and data">
        <p>
          For account access, data requests or deletion help, email <Mail />. You can also delete
          your account yourself from the account menu.
        </p>
      </Section>
      <Section title="Security reports">
        <p>
          Report vulnerabilities privately through{" "}
          <a href={`${REPOSITORY}/security/advisories/new`}>GitHub</a>, not in public issues.
        </p>
      </Section>
      <Section title="Guides">
        <ul>
          <li>
            <a href={`${REPOSITORY}#install`}>Install the Claude Code or Codex plugin</a>
          </li>
          <li>
            <a href={`${REPOSITORY}/blob/main/docs/LOCAL-WORKERS.md`}>Connect a machine to the hosted Studio</a>
          </li>
          <li>
            <a href={`${REPOSITORY}#limits`}>Known limits</a>
          </li>
        </ul>
      </Section>
      <p className="legal-note">Support is best effort. Most issues get a reply within a few days.</p>
    </>
  );
}

export default function Legal({ page }: { page: LegalPage }) {
  useEffect(() => {
    applyStoredTheme();
    const previous = document.title;
    document.title = `${TITLES[page]} · Parallax`;
    return () => {
      document.title = previous;
    };
  }, [page]);
  return (
    <div className="pub-page">
      <a className="skip-link" href="#public-main">
        Skip to content
      </a>
      <header className="pub-header">
        <a className="pub-brand" href="/" aria-label="Parallax home">
          <Mark />
          Parallax
        </a>
        <nav aria-label="Site">
          <ThemeToggle />
        </nav>
      </header>
      <main className="legal-main" id="public-main" tabIndex={-1}>
        <article className="legal">
          <h1>{TITLES[page]}</h1>
          {page !== "support" && <p className="legal-updated">Last updated {UPDATED}</p>}
          {page === "privacy" ? <Privacy /> : page === "terms" ? <Terms /> : <Support />}
        </article>
      </main>
      <PublicFooter />
    </div>
  );
}
