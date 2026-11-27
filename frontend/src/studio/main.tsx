import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Studio from "./Studio";
// The same two typefaces as the original page, bundled so nothing loads from another site.
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow-condensed/700.css";
import "@fontsource/barlow-condensed/700-italic.css";
import "./studio.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Studio />
  </StrictMode>,
);
