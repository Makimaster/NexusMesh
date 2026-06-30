import axios from "axios";

export const http = axios.create({
  baseURL: "http://localhost:8000/api/v1",
  timeout: 10000,
});
