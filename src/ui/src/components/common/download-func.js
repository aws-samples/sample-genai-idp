/* eslint-disable indent */
import * as XLSX from 'xlsx';

// eslint-disable-next-line prettier/prettier
export const onImportExcelAsync = (file) => new Promise((resolve, reject) => {
    // Obtener el objeto del archivo cargado
    const { files } = file.target;
    // Leer el archivo a través del objeto FileReader

    const fileReader = new FileReader();
    fileReader.onload = (event) => {
      const { result } = event.target;
      // Leer en secuencia binaria para obtener todo el objeto de tabla de Excel
      const workbook = XLSX.read(result, { type: 'binary' });
      let data = []; // almacena los datos obtenidos
      // recorre cada hoja de trabajo para leer (aquí solo se lee la primera tabla por defecto)
      // eslint-disable-next-line no-restricted-syntax
      for (const sheet in workbook.Sheets) {
        // eslint-disable-next-line no-prototype-builtins
        if (workbook.Sheets.hasOwnProperty(sheet)) {
          // usa el método sheet_to_json para convertir Excel a datos json
          data = data.concat(XLSX.utils.sheet_to_json(workbook.Sheets[sheet]));
          // break; // Si solo se toma la primera tabla, descomenta esta línea
        }
      }
      resolve(data);

      // Aquí puede lanzar una solicitud relacionada para un error de tipo de archivo incorrecto
    };
    fileReader.onerror = reject;
    // Abre el archivo en modo binario
    fileReader.readAsBinaryString(files[0]);
  });

export const exportToExcel = async (data, nameFile) => {
  if (data.length > 0) {
    const wb = XLSX.utils.book_new();

    const ws = XLSX.utils.json_to_sheet(data, { origin: 'A2' });
    XLSX.utils.sheet_add_aoa(ws, []); // heading: array of arrays

    XLSX.utils.book_append_sheet(wb, ws);

    XLSX.writeFile(wb, `${nameFile}.xlsx`);
  }
};

export const exportToTextFile = async (text, nameFile) => {
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${nameFile}.txt`;
  link.click();
  URL.revokeObjectURL(url);
};
