import axios from "axios";

// Use relative baseURL so Vite proxy can route to the API (and later the Gateway)
export const api = axios.create({
  baseURL: "/api",
});
