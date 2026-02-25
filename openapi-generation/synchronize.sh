#!/bin/bash

FILE="api.yaml"
if [ "$(git ls-files -s ${FILE})" = unmodified ] ; then
    cp -v ../../data-exchange-api/api.yaml .
else
    echo "Refusing to overwrite modified file ${FILE}"
    exit 1
fi
