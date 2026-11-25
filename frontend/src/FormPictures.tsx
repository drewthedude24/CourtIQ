import { FORM_COLUMNS, formatNumber } from "./format";
import type { Shot } from "./types";

// Where each form number of one shot was read: that frame, cropped to the shooter, with the
// joints the number uses drawn in green (vision/form_pictures.py). Small, in one row.
export default function FormPictures({ shot }: { shot: Shot }) {
  const columns = FORM_COLUMNS.filter((column) => shot.pictures[column.key]);
  if (columns.length === 0) return null;

  return (
    <section className="form-pictures">
      <p className="detail caption">
        Shot {shot.shot_number}: the frame each number was read on. Green is what was measured. Knee
        and arm come from heights, not the drawn angle, so from behind the lines can look straighter.
      </p>
      <div>
        {columns.map((column) => (
          <figure key={column.key}>
            <img src={shot.pictures[column.key]} alt={`Shot ${shot.shot_number}, ${column.label}`} />
            <figcaption>
              {column.label}{" "}
              <span className="detail">{formatNumber(shot[column.key], column.digits, column.unit)}</span>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}
