import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "./auth";
import { App } from "./App";
import { ServerProvider } from "./server";
import "./styles.css";

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
