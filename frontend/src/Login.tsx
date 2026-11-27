import { useState, type FormEvent } from "react";
import shooter from "./shooter.jpg";

type Props = {
  // Called with the account's email once the server has set the login cookie.
  onLoggedIn: (email: string) => void;
};

// Log in with an email. A new email makes a new account. Shown instead of the page until the
// browser is logged in.
export default function Login({ onLoggedIn }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email") }),
      });
      const answer = await response.json();
      if (response.ok) onLoggedIn(answer.email);
      else setError(answer.detail); // The server's sentence, like "Enter a real email address."
    } catch {
      setError("Couldn't reach the server. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel welcome">
      <img src={shooter} alt="A player in mid-air on a jump shot, seen from behind, with the hoop ahead" />
      <div>
        <h2>Log in to see your sessions.</h2>
        <p className="detail">Just your email. A new email starts a new account.</p>
        <form className="login" onSubmit={submit}>
          <label>
            Email
            <input name="email" type="email" autoComplete="email" required />
          </label>
          {error && <p className="login-error" role="alert">{error}</p>}
          <button className={busy ? "button disabled" : "button"} type="submit" disabled={busy}>
            Log in
          </button>
        </form>
      </div>
    </section>
  );
}
