// Rendered PDF page with bounding boxes drawn over it. The API renders pages at 72 dpi (zoom 1.0),
// so one image pixel = one PDF point and bboxes can be placed as percentages of the image size.
import { useState } from "react";
import { pageUrl } from "../api.js";

export default function PageImage({ docId, page, boxes = [], selected, onSelect }) {
  const [size, setSize] = useState(null);
  return (
    <div className="pageimg">
      <img src={pageUrl(docId, page)} alt={`Page ${page} of ${docId}`}
           onLoad={(e) => setSize({ w: e.target.naturalWidth, h: e.target.naturalHeight })} />
      {size && boxes.filter((b) => b.bbox).map((b, i) => {
        const [x0, y0, x1, y1] = b.bbox;
        return (
          <div key={i} className={`bbox ${selected === b.key ? "bbox-sel" : ""}`}
               onClick={() => onSelect?.(b.key)}
               style={{ left: `${(x0 / size.w) * 100}%`, top: `${(y0 / size.h) * 100}%`,
                        width: `${((x1 - x0) / size.w) * 100}%`, height: `${((y1 - y0) / size.h) * 100}%`,
                        cursor: onSelect ? "pointer" : "default" }}>
            {b.label && <span>{b.label}</span>}
          </div>
        );
      })}
    </div>
  );
}
