import type { Session } from "./types";

// Sends the video to the API. fetch() can't say how much of a file has gone out, so this
// uses the older XMLHttpRequest, which calls onProgress as the bytes are sent.
export function uploadVideo(
  file: File,
  onProgress: (sent: number, total: number) => void,
): Promise<Session> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    formData.append("file", file);

    const request = new XMLHttpRequest();
    request.open("POST", "/api/sessions");
    request.responseType = "json";
    request.upload.onprogress = (event) => onProgress(event.loaded, event.total);
    request.onload = () => {
      if (request.status === 202) resolve(request.response);
      else reject(new Error("Upload failed"));
    };
    request.onerror = () => reject(new Error("Upload failed"));
    request.send(formData);
  });
}
