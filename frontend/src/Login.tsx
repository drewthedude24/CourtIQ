import { useState, type FormEvent } from "react";
import shooter from "./shooter.jpg";

type Props = {
  // Called with the account's email once the server has set the login cookie.
  onLoggedIn: (email: string) => void;
};

// Log in, or make an account. Shown instead of the page until the browser is logged in.
export default function Login({ onLoggedIn }: Props) {
  const [signingUp, setSigningUp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(signingUp ? "/api/signup" : "/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      const answer = await response.json();
      if (response.ok) onLoggedIn(answer.email);
      else setError(answer.detail); // The server's sentence, like "Wrong email or password."
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
        <h2>{signingUp ? "Make your account." : "Log in to see your sessions."}</h2>
        <p className="detail">Your clips, shots and form numbers are only shown to you.</p>
        <form className="login" onSubmit={submit}>
          <label>
            Email
            <input name="email" type="email" autoComplete="email" required />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete={signingUp ? "new-password" : "current-password"}
              minLength={signingUp ? 8 : undefined}
              required
            />
          </label>
          {signingUp && <p className="detail">At least 8 characters.</p>}
          {error && <p className="login-error" role="alert">{error}</p>}
          <button className={busy ? "button disabled" : "button"} type="submit" disabled={busy}>
            {signingUp ? "Make account" : "Log in"}
          </button>
        </form>
        <button
          className="text-button"
          type="button"
          onClick={() => {
            setSigningUp(!signingUp);
            setError(null);
          }}
        >
          {signingUp ? "Have an account? Log in" : "New here? Make an account"}
        </button>
      </div>
    </section>
  );
}
