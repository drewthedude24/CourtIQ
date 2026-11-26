import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
// The two typefaces, bundled with the page so nothing is loaded from another site.
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow-condensed/700.css";
import "@fontsource/barlow-condensed/700-italic.css";
import "./App.css";

// The ! tells TypeScript this element is always there (it is in index.html).
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
