import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AuthProvider } from "./auth";
import { App } from "./App";
import { ServerProvider } from "./server";
import "./styles.css";
import { applyTheme } from "./i18n";

applyTheme();
document.documentElement.lang = localStorage.getItem("dm_lang") === "en" ? "en" : "ru";

const router = createBrowserRouter([{
  path: "*",
  element: <AuthProvider><ServerProvider><App /></ServerProvider></AuthProvider>,
}]);

createRoot(document.getElementById("root")!).render(
  <StrictMode><RouterProvider router={router}/></StrictMode>,
);
