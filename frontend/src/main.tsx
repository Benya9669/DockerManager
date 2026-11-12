import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./auth";
import { App } from "./App";
import { ServerProvider } from "./server";
import "./styles.css";
import { applyTheme } from "./i18n";

applyTheme();
document.documentElement.lang = localStorage.getItem("dm_lang") === "en" ? "en" : "ru";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ServerProvider>
          <App />
        </ServerProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
