"use client";
import { useEffect, useRef, useState } from "react";

export default function ExpandablePostText({ text, className = "" }: { text: string; className?: string }) {
  const [expanded, setExpanded] = useState(false);
  const [canExpand, setCanExpand] = useState(false);
  const body = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    const element = body.current;
    if (!element || expanded) return;
    const update = () => setCanExpand(element.scrollHeight > element.clientHeight + 1);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, expanded]);
  return <div className="post-text-wrap">
    <p ref={body} className={`${className} post-text${expanded ? "" : " post-text-clamped"}`}>{text}</p>
    {(canExpand || expanded) && <button type="button" className="post-text-toggle" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "Thu gọn" : "Xem thêm"}</button>}
  </div>;
}
