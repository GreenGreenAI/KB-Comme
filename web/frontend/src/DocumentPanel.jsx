import { useEffect, useState } from "react";
import {
  checkTradeDocuments,
  confirmDocumentFields,
  listTradeDocuments,
  uploadTradeDocument,
} from "./api.js";

const DOCUMENT_TYPE = {
  letter_of_credit: "신용장",
  commercial_invoice: "상업송장",
  packing_list: "포장명세서",
  bill_of_lading: "선하증권",
  purchase_order: "구매주문서",
  contract: "계약서",
  customs_declaration: "수출입신고서",
  application_form: "신청서",
  unknown: "유형 확인 필요",
};

const FIELD = {
  document_number: "문서번호",
  currency: "통화",
  amount: "금액",
  issue_date: "발행일",
  shipment_date: "선적일",
  payment_date: "결제일",
  expiry_date: "유효기일",
  applicant: "개설의뢰인·매수인",
  beneficiary: "수익자·매도인",
  goods_description: "품명",
  port_of_loading: "선적항",
  port_of_discharge: "양륙항",
};

function editableFields(document) {
  return Object.fromEntries(
    (document?.extraction?.fields ?? []).map((field) => [
      field.field_name,
      field.confirmed ? field.confirmed_value : field.normalized_value,
    ]),
  );
}

function expectedFields(trade) {
  if (!trade) return {};
  return Object.fromEntries(
    Object.entries({
      currency: trade.currency,
      amount: trade.amount,
      payment_date: trade.expected_payment_date,
    }).filter(([, value]) => value !== null && value !== undefined && value !== ""),
  );
}

export default function DocumentPanel({ trades = [], signedIn = false }) {
  const [caseId, setCaseId] = useState(trades[0]?.case_id ?? "");
  const [documents, setDocuments] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [values, setValues] = useState({});
  const [file, setFile] = useState(null);
  const [check, setCheck] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const selected = documents.find((item) => item.document_id === selectedId) ?? null;
  const trade = trades.find((item) => item.case_id === caseId) ?? trades[0];

  useEffect(() => {
    if (!signedIn || !caseId) return undefined;
    let active = true;
    listTradeDocuments(caseId)
      .then((items) => {
        if (!active) return;
        setDocuments(items);
        const newest = items.at(-1);
        setSelectedId(newest?.document_id ?? "");
        setValues(editableFields(newest));
      })
      .catch((reason) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
    };
  }, [caseId, signedIn]);

  if (trades.length === 0) return null;
  if (!signedIn) {
    return (
      <section className="decision-section document-panel" aria-labelledby="documents-title">
        <h3 id="documents-title">거래 문서 검토</h3>
        <p className="decision-empty">원본 문서는 기업별로 격리하므로 로그인 후 업로드할 수 있습니다.</p>
      </section>
    );
  }

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (reason) {
      setError(reason.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="decision-section document-panel" aria-labelledby="documents-title">
      <header>
        <div>
          <h3 id="documents-title">거래 문서 검토</h3>
          <p>원본은 암호화 저장하며 추출값은 확인 전까지 거래 사실로 사용하지 않습니다.</p>
        </div>
        {trades.length > 1 ? (
          <label>
            거래
            <select
              value={caseId}
              onChange={(event) => {
                setCaseId(event.target.value);
                setDocuments([]);
                setSelectedId("");
                setCheck(null);
              }}
            >
              {trades.map((item) => (
                <option key={item.case_id} value={item.case_id}>{item.case_id}</option>
              ))}
            </select>
          </label>
        ) : null}
      </header>

      <div className="document-upload">
        <label>
          문서 선택
          <input
            type="file"
            accept=".pdf,.txt,.png,.jpg,.jpeg"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <button
          type="button"
          disabled={!file || busy}
          onClick={() => run(async () => {
            const uploaded = await uploadTradeDocument(caseId, file);
            setDocuments((current) => {
              const withoutDuplicate = current.filter(
                (item) => item.document_id !== uploaded.document_id,
              );
              return [...withoutDuplicate, uploaded];
            });
            setSelectedId(uploaded.document_id);
            setValues(editableFields(uploaded));
            setFile(null);
            setCheck(null);
          })}
        >
          업로드·추출
        </button>
      </div>

      {error ? <p className="document-error" role="alert">{error}</p> : null}
      {documents.length > 0 ? (
        <div className="document-tabs" role="tablist" aria-label="업로드 문서">
          {documents.map((document) => (
            <button
              type="button"
              role="tab"
              aria-selected={selectedId === document.document_id}
              key={document.document_id}
              onClick={() => {
                setSelectedId(document.document_id);
                setValues(editableFields(document));
              }}
            >
              {document.filename}
            </button>
          ))}
        </div>
      ) : (
        <p className="decision-empty">아직 업로드한 문서가 없습니다.</p>
      )}

      {selected ? (
        <div className="document-extraction">
          <p>
            <b>{DOCUMENT_TYPE[selected.document_type] ?? selected.document_type}</b>
            <span>{selected.extraction_state === "needs_ocr" ? "OCR 필요" : "텍스트 추출 완료"}</span>
            <code>{selected.content_hash}</code>
          </p>
          {selected.extraction?.issues?.map((issue) => (
            <p className="document-warning" key={issue}>{issue}</p>
          ))}
          {(selected.extraction?.fields ?? []).length > 0 ? (
            <div className="extracted-fields">
              {selected.extraction.fields.map((field) => (
                <label key={field.field_name}>
                  <span>
                    {FIELD[field.field_name] ?? field.field_name}
                    <small>
                      신뢰도 {Math.round(field.confidence * 100)}% ·
                      {field.location.page ? ` ${field.location.page}쪽` : ""} {field.location.line}행
                    </small>
                  </span>
                  <input
                    value={values[field.field_name] ?? ""}
                    onChange={(event) =>
                      setValues((current) => ({
                        ...current,
                        [field.field_name]: event.target.value,
                      }))
                    }
                  />
                </label>
              ))}
            </div>
          ) : null}
          <button
            type="button"
            disabled={Object.keys(values).length === 0 || busy}
            onClick={() => run(async () => {
              const confirmed = await confirmDocumentFields(selected.document_id, values);
              setDocuments((current) =>
                current.map((item) =>
                  item.document_id === confirmed.document_id ? confirmed : item
                ),
              );
              setValues(editableFields(confirmed));
            })}
          >
            추출 필드 확인 저장
          </button>
        </div>
      ) : null}

      <button
        type="button"
        className="document-check"
        disabled={documents.length === 0 || busy}
        onClick={() => run(async () => {
          setCheck(await checkTradeDocuments(caseId, expectedFields(trade)));
        })}
      >
        거래·문서 정합성 검사
      </button>

      {check ? (
        <div className={`document-findings ${check.review_required ? "required" : "clear"}`} aria-live="polite">
          <b>{check.review_required ? "사람의 확인이 필요한 불일치" : "확인된 불일치 없음"}</b>
          {check.findings.length > 0 ? (
            <ul>
              {check.findings.map((finding, index) => (
                <li key={`${finding.kind}:${finding.field}:${index}`}>
                  {FIELD[finding.field] ?? finding.field} · {finding.reason}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
