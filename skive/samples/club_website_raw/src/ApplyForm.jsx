// author: 김민수
import { useState } from "react";

export default function ApplyForm({ onSubmit }) {
  const [name, setName] = useState("");
  const [motivation, setMotivation] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({ name, motivation });
  };

  return (
    <form onSubmit={handleSubmit}>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="이름" />
      <textarea value={motivation} onChange={(e) => setMotivation(e.target.value)} />
      <button type="submit">지원하기</button>
    </form>
  );
}
