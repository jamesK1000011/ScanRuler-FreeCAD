# SPDX-License-Identifier: AGPL-3.0-only
# Ported from ScanRuler by Stefan Hermann (CNC Kitchen),
# github.com/CNCKitchen/ScanRuler: src/core/field/colormap.ts,
# src/core/field/colormapData.ts and src/state/palette.ts.
#
# One set of rules for every map painted on the scan: the deviation from a
# nominal part, the wall thickness of the part itself, a mesh edit against
# the scan. Only the domain and its direction differ, so all of them are
# painted by the same function through whichever colour map is chosen in the
# settings, the same one for every map and every legend. Pure numpy: no
# FreeCAD, Qt or Agent Link import, so it loads anywhere.
#
# The tables behind every map but jet are 256 colours each, from the low end
# of the ramp to the high, six hex digits apiece, copied byte for byte from
# ScanRuler's colormapData.ts, which copied them from the R package
# viridisLite (data-raw/option[A-H].csv). Their authors: magma, inferno,
# plasma and viridis by Nathaniel J. Smith, Stefan van der Walt and Eric
# Firing, for matplotlib; cividis by Jamie R. Nunez, Christopher R. Anderton
# and Ryan S. Renslow; rocket and mako by Michael L. Waskom, for seaborn;
# turbo by Anton Mikhailov, Google. The tables are viridisLite's, under its
# MIT License:
#
#   Copyright (c) 2015 Simon Garnier
#
#   Permission is hereby granted, free of charge, to any person obtaining a
#   copy of this software and associated documentation files (the
#   "Software"), to deal in the Software without restriction, including
#   without limitation the rights to use, copy, modify, merge, publish,
#   distribute, sublicense, and/or sell copies of the Software, and to permit
#   persons to whom the Software is furnished to do so, subject to the
#   following conditions:
#
#   The above copyright notice and this permission notice shall be included
#   in all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#   OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
#   MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
#   NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
#   DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
#   OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
#   USE OR OTHER DEALINGS IN THE SOFTWARE.

import math

import numpy as np

# The unmeasured scan surface: a machined-aluminium grey. Doubles as the
# "nothing to measure here" colour on any map: an unmeasured patch reads as
# bare material, not as a measurement. The same on every map, and on none.
UNMEASURED_RGB = (126, 131, 138)

# The eight accent colours everything numbered on screen is drawn in
# (elements, point pairs). Starts on the CNC Kitchen blue, so the first of
# anything is always that blue.
PALETTE = ("#1877c0", "#e8590c", "#2e7d46", "#b5179e", "#c99a0a", "#0f9b9b", "#b3361c", "#6d4bbd")

# The legend's ramp carries this many ticks.
TICKS = 9

_VIRIDIS = (
    "44015444025645045745055946075a46085c460a5d460b5e470d60470e61471063471164"
    "47136548146748166848176948186a481a6c481b6d481c6e481d6f481f70482071482173"
    "482374482475482576482677482878482979472a7a472c7a472d7b472e7c472f7d46307e"
    "46327e46337f463480453581453781453882443983443a83443b84433d84433e85423f85"
    "4240864241864142874144874045884046883f47883f48893e49893e4a893e4c8a3d4d8a"
    "3d4e8a3c4f8a3c508b3b518b3b528b3a538b3a548c39558c39568c38588c38598c375a8c"
    "375b8d365c8d365d8d355e8d355f8d34608d34618d33628d33638d32648e32658e31668e"
    "31678e31688e30698e306a8e2f6b8e2f6c8e2e6d8e2e6e8e2e6f8e2d708e2d718e2c718e"
    "2c728e2c738e2b748e2b758e2a768e2a778e2a788e29798e297a8e297b8e287c8e287d8e"
    "277e8e277f8e27808e26818e26828e26828e25838e25848e25858e24868e24878e23888e"
    "23898e238a8d228b8d228c8d228d8d218e8d218f8d21908d21918c20928c20928c20938c"
    "1f948c1f958b1f968b1f978b1f988b1f998a1f9a8a1e9b8a1e9c891e9d891f9e891f9f88"
    "1fa0881fa1881fa1871fa28720a38620a48621a58521a68522a78522a88423a98324aa83"
    "25ab8225ac8226ad8127ad8128ae8029af7f2ab07f2cb17e2db27d2eb37c2fb47c31b57b"
    "32b67a34b67935b77937b87838b9773aba763bbb753dbc743fbc7340bd7242be7144bf70"
    "46c06f48c16e4ac16d4cc26c4ec36b50c46a52c56954c56856c66758c7655ac8645cc863"
    "5ec96260ca6063cb5f65cb5e67cc5c69cd5b6ccd5a6ece5870cf5773d05675d05477d153"
    "7ad1517cd2507fd34e81d34d84d44b86d54989d5488bd6468ed64590d74393d74195d840"
    "98d83e9bd93c9dd93ba0da39a2da37a5db36a8db34aadc32addc30b0dd2fb2dd2db5de2b"
    "b8de29bade28bddf26c0df25c2df23c5e021c8e020cae11fcde11dd0e11cd2e21bd5e21a"
    "d8e219dae319dde318dfe318e2e418e5e419e7e419eae51aece51befe51cf1e51df4e61e"
    "f6e620f8e621fbe723fde725"
)

_MAGMA = (
    "00000401000501010601010802010902020b02020d03030f030312040414050416060518"
    "06051a07061c08071e0907200a08220b09240c09260d0a290e0b2b100b2d110c2f120d31"
    "130d34140e36150e38160f3b180f3d19103f1a10421c10441d11471e114920114b21114e"
    "22115024125325125527125829115a2a115c2c115f2d11612f1163311165331067341069"
    "36106b38106c390f6e3b0f703d0f713f0f72400f74420f75440f76451077471078491078"
    "4a10794c117a4e117b4f127b51127c52137c54137d56147d57157e59157e5a167e5c167f"
    "5d177f5f187f601880621980641a80651a80671b80681c816a1c816b1d816d1d816e1e81"
    "701f81721f817320817521817621817822817922827b23827c23827e2482802582812581"
    "8326818426818627818827818928818b29818c29818e2a81902a81912b81932b80942c80"
    "962c80982d80992d809b2e7f9c2e7f9e2f7fa02f7fa1307ea3307ea5317ea6317da8327d"
    "aa337dab337cad347cae347bb0357bb2357bb3367ab5367ab73779b83779ba3878bc3978"
    "bd3977bf3a77c03a76c23b75c43c75c53c74c73d73c83e73ca3e72cc3f71cd4071cf4070"
    "d0416fd2426fd3436ed5446dd6456cd8456cd9466bdb476adc4869de4968df4a68e04c67"
    "e24d66e34e65e44f64e55064e75263e85362e95462ea5661eb5760ec5860ed5a5fee5b5e"
    "ef5d5ef05f5ef1605df2625df2645cf3655cf4675cf4695cf56b5cf66c5cf66e5cf7705c"
    "f7725cf8745cf8765cf9785df9795df97b5dfa7d5efa7f5efa815ffb835ffb8560fb8761"
    "fc8961fc8a62fc8c63fc8e64fc9065fd9266fd9467fd9668fd9869fd9a6afd9b6bfe9d6c"
    "fe9f6dfea16efea36ffea571fea772fea973feaa74feac76feae77feb078feb27afeb47b"
    "feb67cfeb77efeb97ffebb81febd82febf84fec185fec287fec488fec68afec88cfeca8d"
    "fecc8ffecd90fecf92fed194fed395fed597fed799fed89afdda9cfddc9efddea0fde0a1"
    "fde2a3fde3a5fde5a7fde7a9fde9aafdebacfcecaefceeb0fcf0b2fcf2b4fcf4b6fcf6b8"
    "fcf7b9fcf9bbfcfbbdfcfdbf"
)

_PLASMA = (
    "0d088710078813078916078a19068c1b068d1d068e20068f220690240691260591280592"
    "2a05932c05942e05952f059631059733059735049837049938049a3a049a3c049b3e049c"
    "3f049c41049d43039e44039e46039f48039f4903a04b03a14c02a14e02a25002a25102a3"
    "5302a35502a45601a45801a45901a55b01a55c01a65e01a66001a66100a76300a76400a7"
    "6600a76700a86900a86a00a86c00a86e00a86f00a87100a87201a87401a87501a87701a8"
    "7801a87a02a87b02a87d03a87e03a88004a88104a78305a78405a78606a68707a68808a6"
    "8a09a58b0aa58d0ba58e0ca48f0da4910ea3920fa39410a29511a19613a19814a099159f"
    "9a169f9c179e9d189d9e199da01a9ca11b9ba21d9aa31e9aa51f99a62098a72197a82296"
    "aa2395ab2494ac2694ad2793ae2892b02991b12a90b22b8fb32c8eb42e8db52f8cb6308b"
    "b7318ab83289ba3388bb3488bc3587bd3786be3885bf3984c03a83c13b82c23c81c33d80"
    "c43e7fc5407ec6417dc7427cc8437bc9447aca457acb4679cc4778cc4977cd4a76ce4b75"
    "cf4c74d04d73d14e72d24f71d35171d45270d5536fd5546ed6556dd7566cd8576bd9586a"
    "da5a6ada5b69db5c68dc5d67dd5e66de5f65de6164df6263e06363e16462e26561e26660"
    "e3685fe4695ee56a5de56b5de66c5ce76e5be76f5ae87059e97158e97257ea7457eb7556"
    "eb7655ec7754ed7953ed7a52ee7b51ef7c51ef7e50f07f4ff0804ef1814df1834cf2844b"
    "f3854bf3874af48849f48948f58b47f58c46f68d45f68f44f79044f79143f79342f89441"
    "f89540f9973ff9983ef99a3efa9b3dfa9c3cfa9e3bfb9f3afba139fba238fca338fca537"
    "fca636fca835fca934fdab33fdac33fdae32fdaf31fdb130fdb22ffdb42ffdb52efeb72d"
    "feb82cfeba2cfebb2bfebd2afebe2afec029fdc229fdc328fdc527fdc627fdc827fdca26"
    "fdcb26fccd25fcce25fcd025fcd225fbd324fbd524fbd724fad824fada24f9dc24f9dd25"
    "f8df25f8e125f7e225f7e425f6e626f6e826f5e926f5eb27f4ed27f3ee27f3f027f2f227"
    "f1f426f1f525f0f724f0f921"
)

_INFERNO = (
    "00000401000501010601010802010a02020c02020e030210040312040314050417060419"
    "07051b08051d09061f0a07220b07240c08260d08290e092b10092d110a30120a32140b34"
    "150b37160b39180c3c190c3e1b0c411c0c431e0c451f0c48210c4a230c4c240c4f260c51"
    "280b53290b552b0b572d0b592f0a5b310a5c320a5e340a5f3609613809623909633b0964"
    "3d09653e0966400a67420a68440a68450a69470b6a490b6a4a0c6b4c0c6b4d0d6c4f0d6c"
    "510e6c520e6d540f6d550f6d57106e59106e5a116e5c126e5d126e5f136e61136e62146e"
    "64156e65156e67166e69166e6a176e6c186e6d186e6f196e71196e721a6e741a6e751b6e"
    "771c6d781c6d7a1d6d7c1d6d7d1e6d7f1e6c801f6c82206c84206b85216b87216b88226a"
    "8a226a8c23698d23698f24699025689225689326679526679727669827669a28659b2964"
    "9d29649f2a63a02a63a22b62a32c61a52c60a62d60a82e5fa92e5eab2f5ead305dae305c"
    "b0315bb1325ab3325ab43359b63458b73557b93556ba3655bc3754bd3853bf3952c03a51"
    "c13a50c33b4fc43c4ec63d4dc73e4cc83f4bca404acb4149cc4248ce4347cf4446d04545"
    "d24644d34743d44842d54a41d74b3fd84c3ed94d3dda4e3cdb503bdd513ade5238df5337"
    "e05536e15635e25734e35933e45a31e55c30e65d2fe75e2ee8602de9612bea632aeb6429"
    "eb6628ec6726ed6925ee6a24ef6c23ef6e21f06f20f1711ff1731df2741cf3761bf37819"
    "f47918f57b17f57d15f67e14f68013f78212f78410f8850ff8870ef8890cf98b0bf98c0a"
    "f98e09fa9008fa9207fa9407fb9606fb9706fb9906fb9b06fb9d07fc9f07fca108fca309"
    "fca50afca60cfca80dfcaa0ffcac11fcae12fcb014fcb216fcb418fbb61afbb81dfbba1f"
    "fbbc21fbbe23fac026fac228fac42afac62df9c72ff9c932f9cb35f8cd37f8cf3af7d13d"
    "f7d340f6d543f6d746f5d949f5db4cf4dd4ff4df53f4e156f3e35af3e55df2e661f2e865"
    "f2ea69f1ec6df1ed71f1ef75f1f179f2f27df2f482f3f586f3f68af4f88ef5f992f6fa96"
    "f8fb9af9fc9dfafda1fcffa4"
)

_CIVIDIS = (
    "00204d00214e00225000225200235300245500255700255800265a00275c00275e002860"
    "002961002a63002a65002b67002c69002c6a002d6c002e6e002e6f002f6f002f6f00306f"
    "00306f00316f00326f00336f00336f00346f00356e01366e06366e0b376e0f386e12386d"
    "15396d183a6d1a3b6d1d3b6d1f3c6d213d6d233e6c243e6c263f6c28406c2a406c2b416c"
    "2d426c2e436c30436c31446b32456b34456b35466b36476b38486b39486b3a496b3b4a6b"
    "3d4a6b3e4b6b3f4c6b404d6b414d6b424e6b434f6b444f6b46506b47516b48526b49526b"
    "4a536b4b546c4c546c4d556c4e566c4f576c50576c51586c52596c53596c545a6c555b6d"
    "565c6d575c6d585d6d595e6d595f6d5a5f6d5b606e5c616e5d616e5e626e5f636e60646f"
    "61646f62656f63666f64666f646770656870666970676970686a71696b716a6c716b6c71"
    "6c6d726c6e726d6e726e6f736f7073707173717174727274727374737475747475757575"
    "7676767777767877777878777979777a7a787b7a787c7b787d7c787e7d787f7d78807e79"
    "817f798280798380798481798482798583798683798784798885798986798a87798b8779"
    "8c88798d89798e8a798f8a79908b79918c78928d78938e78948e78958f78969078979178"
    "9892789992789a93779b94779c95779d96779e96779f9777a09877a19976a29a76a39a76"
    "a49b76a59c76a69d75a89e75a99f75aa9f75aba074aca174ada274aea374afa473b0a473"
    "b1a573b2a672b3a772b4a872b5a971b6a971b7aa71b8ab70b9ac70baad70bbae6fbcaf6f"
    "beaf6fbfb06ec0b16ec1b26dc2b36dc3b46dc4b56cc5b56cc6b66bc7b76bc8b86ac9b96a"
    "cbba69ccbb69cdbc68cebc68cfbd67d0be67d1bf66d2c066d3c165d4c264d6c364d7c463"
    "d8c563d9c562dac661dbc761dcc860ddc95fdeca5fe0cb5ee1cc5de2cd5ce3ce5ce4cf5b"
    "e5d05ae6d159e8d259e9d358ead357ebd456ecd555edd654efd753f0d852f1d951f2da50"
    "f3db4ff4dc4ef6dd4df7de4cf8df4bf9e04afae149fbe248fde346fee445ffe544ffe642"
    "ffe742ffe843ffe944ffea46"
)

_MAKO = (
    "0b04050d04060e05080f060910060a11070c12080d13090f140910150a12160b13170c15"
    "180d16190e181a0e191b0f1a1c101c1d111d1e111f1f1220201322211423221425231526"
    "24162825172926172b27182d28192e291930291a312a1b332b1c352c1c362d1d382e1e39"
    "2e1e3b2f1f3d30203e31214031214232224333234534244734254835254a35264c36274d"
    "37284f372851382953382a54392b563a2c583a2c593b2d5b3b2e5d3b2f5f3c30603c3162"
    "3d31643d32663e33673e34693e356b3f366d3f366f3f3770403872403974403a76403b78"
    "403c79413d7b413e7d413e7f413f8041408241418441428541438741448840468a40478b"
    "40488d40498e3f4a8f3f4b903f4c923e4d933e4f943e50953d51953d52963c53973c5598"
    "3b56983b57993b589a3a599a3a5b9b3a5c9b395d9c395e9c385f9c38619d38629d38639d"
    "37649e37659e37669e37689f36699f366a9f366b9f366ca0366da0366fa03670a03671a0"
    "3572a13573a13574a13575a13576a23578a23579a2357aa2357ba3357ca3357da3357ea4"
    "347fa43480a43482a43483a53484a53485a53486a53487a63488a63489a6348ba6348ca7"
    "348da7348ea7348fa73490a83491a83492a83493a83495a93496a93497a93498a93499aa"
    "349aaa359baa359caa359eaa359fab35a0ab35a1ab36a2ab36a3ab36a4ab37a5ac37a6ac"
    "37a8ac38a9ac38aaac39abac39acac3aadac3aaead3bafad3cb1ad3cb2ad3db3ad3eb4ad"
    "3fb5ad3fb6ad40b7ad41b8ad42b9ad43baad44bcad45bdad46bead47bfad48c0ad49c1ad"
    "4bc2ad4cc3ad4dc4ad4fc5ad50c6ad52c7ad53c9ad55caad57cbad59ccad5bcdad5ecdad"
    "60ceac62cfac65d0ad68d1ad6ad2ad6dd3ad70d4ad73d4ad76d5ae79d6ae7cd6af7fd7af"
    "82d8b085d9b188d9b18bdab28edbb391dbb494dcb596ddb599ddb69cdeb79edfb8a1dfb9"
    "a4e0bba6e1bca9e1bdabe2beaee3c0b0e4c1b2e4c2b5e5c4b7e6c5b9e6c7bbe7c8bee8ca"
    "c0e9ccc2e9cdc4eacfc6ebd1c8ecd2caedd4ccedd6ceeed7d0efd9d2f0dbd4f1dcd6f1de"
    "d8f2e0daf3e1dcf4e3def5e5"
)

_ROCKET = (
    "03051a04051a05061b06071c07071d08081e0a091f0b09200d0a210e0b22100b23110c24"
    "130d25140e26160e27170f28180f291a102a1b112b1d112c1e122d20122e211330221331"
    "2414322514332715342815352a16362b16372d17382e173930173a31183b33183c34193d"
    "35193e37193f381a403a1a413c1a423d1a423f1b43401b44421b45431c46451c47461c48"
    "481c48491d494b1d4a4c1d4b4e1d4b501d4c511e4d531e4d541e4e561e4f581e4f591e50"
    "5b1e515c1e515e1f52601f52611f53631f53641f54661f54681f55691f556b1f566d1f56"
    "6e1f57701f57711f57731f58751f58761f58781f597a1f597b1f597d1f5a7f1e5a811e5a"
    "821e5a841e5a861e5b871e5b891e5b8b1d5b8c1d5b8e1d5b901d5b921c5b931c5b951c5b"
    "971c5b981b5b9a1b5b9c1b5b9e1a5b9f1a5ba11a5ba3195ba4195ba6195aa8185aaa185a"
    "ab185aad1759af1759b01759b21758b41658b51657b71657b91657ba1656bc1656bd1655"
    "bf1654c11754c21753c41753c51852c71951c81951ca1a50cb1b4fcd1c4ece1d4ecf1e4d"
    "d11f4cd2204cd3214bd5224ad62449d72549d82748d92847db2946dc2b46dd2c45de2e44"
    "df2f44e03143e13342e23442e33641e43841e53940e63b40e73d3fe83f3fe8403ee9423e"
    "ea443eeb463eeb483eec4a3eec4c3eed4e3eed503eee523fee543fef5640ef5840ef5a41"
    "f05c42f05e42f06043f16244f16445f16646f26747f26948f26b49f26d4bf26f4cf3714d"
    "f3734ef37450f37651f37852f47a54f47c55f47d57f47f58f4815af4835bf4845df4865e"
    "f58860f58a61f58b63f58d64f58f66f59067f59269f5946bf5966cf5976ef59970f69b71"
    "f69c73f69e75f6a077f6a178f6a37af6a47cf6a67ef6a880f6a981f6ab83f6ad85f6ae87"
    "f6b089f6b18bf6b38df6b48ff6b691f6b893f6b995f6bb97f6bc99f6be9bf6bf9df6c19f"
    "f7c2a2f7c4a4f7c6a6f7c7a8f7c9aaf7caacf7ccaff7cdb1f7cfb3f7d0b5f8d1b8f8d3ba"
    "f8d4bcf8d6bef8d7c0f8d9c3f8dac5f8dcc7f9ddc9f9dfcbf9e0cdf9e2d0f9e3d2f9e5d4"
    "fae6d6fae8d8fae9dafaebdd"
)

_TURBO = (
    "30123b32154333184a341b51351e5836215f37246638276d392a733a2d793b2f803c3286"
    "3d358b3e38913f3b973f3e9c4040a24143a74146ac4249b1424bb5434eba4451bf4454c3"
    "4456c74559cb455ccf455ed34661d64664da4666dd4669e0466be3476ee64771e94773eb"
    "4776ee4778f0477bf2467df44680f64682f84685fa4687fb458afc458cfd448ffe4391fe"
    "4294ff4196ff4099ff3e9bfe3d9efe3ba0fd3aa3fc38a5fb37a8fa35abf833adf731aff5"
    "2fb2f42eb4f22cb7f02ab9ee28bceb27bee925c0e723c3e422c5e220c7df1fc9dd1ecbda"
    "1ccdd81bd0d51ad2d21ad4d019d5cd18d7ca18d9c818dbc518ddc218dec018e0bd19e2bb"
    "19e3b91ae4b61ce6b41de7b21fe9af20eaac22ebaa25eca727eea42aefa12cf09e2ff19b"
    "32f29835f39438f4913cf58e3ff68a43f78746f8844af8804ef97d52fa7a55fa7659fb73"
    "5dfc6f61fc6c65fd6969fd666dfe6271fe5f75fe5c79fe597dff5680ff5384ff5188ff4e"
    "8bff4b8fff4992ff4796fe4499fe429cfe409ffd3fa1fd3da4fc3ca7fc3aa9fb39acfb38"
    "affa37b1f936b4f836b7f735b9f635bcf534bef434c1f334c3f134c6f034c8ef34cbed34"
    "cdec34d0ea34d2e935d4e735d7e535d9e436dbe236dde037dfdf37e1dd37e3db38e5d938"
    "e7d739e9d539ebd339ecd13aeecf3aefcd3af1cb3af2c93af4c73af5c53af6c33af7c13a"
    "f8be39f9bc39faba39fbb838fbb637fcb336fcb136fdae35fdac34fea933fea732fea431"
    "fea130fe9e2ffe9b2dfe992cfe962bfe932afe9029fd8d27fd8a26fc8725fc8423fb8122"
    "fb7e21fa7b1ff9781ef9751df8721cf76f1af66c19f56918f46617f36315f26014f15d13"
    "f05b12ef5811ed5510ec530feb500eea4e0de84b0ce7490ce5470be4450ae2430ae14109"
    "df3f08dd3d08dc3b07da3907d83706d63506d43305d23105d02f05ce2d04cc2b04ca2a04"
    "c82803c52603c32503c12302be2102bc2002b91e02b71d02b41b01b21a01af1801ac1701"
    "a91601a71401a41301a112019e10019b0f01980e01950d01920b018e0a018b0902880802"
    "8507028106027e05027a0403"
)


def _table(hex_):
    """A table written as hex as an (n, 3) uint8 array."""
    return np.frombuffer(bytes.fromhex(hex_), dtype=np.uint8).reshape(-1, 3).copy()


# Jet, pinned so that the middle of the scale is a saturated green: blue,
# cyan, green, yellow, red, the way inspection software reads.
_JET = np.array([[0, 0, 255], [0, 255, 255], [0, 200, 0], [255, 255, 0], [255, 0, 0]], dtype=np.uint8)

_BLUE = (0, 0, 255)
_RED = (220, 0, 0)
_GREEN = (0, 190, 0)


class Colormap:
    """A ramp, and the two colours that stand beyond its ends.

    `under` and `over` are the caps for a reading that is real but off the
    end of the scale: each map's own, and colours it never uses itself, so a
    value off-scale is never confused with one that is merely large."""

    __slots__ = ("id", "label", "hint", "stops", "under", "over")

    def __init__(self, id, label, hint, stops, under, over):
        self.id = id
        self.label = label
        self.hint = hint
        self.stops = stops
        self.under = tuple(under)
        self.over = tuple(over)

    def __repr__(self):
        return f"Colormap({self.id!r}, {len(self.stops)} stops)"


# Every map the settings offer, in the order the original offers them: jet,
# which ScanRuler has always painted, then the eight of the viridis family.
COLORMAPS = (
    Colormap("jet", "Jet", "Blue through cyan, green and yellow to red, a saturated green in the middle — the inspection-software classic. Uneven in lightness, so cyan and yellow show as bands the part does not have", _JET, (0, 0, 110), (130, 0, 0)),
    Colormap("viridis", "Viridis", "Dark blue through teal and green to yellow. Perceptually uniform — an even step in the reading is an even step in colour — and as legible to colour-blind eyes and in greyscale", _table(_VIRIDIS), _BLUE, _RED),
    Colormap("magma", "Magma", "Black through purple and pink to pale cream. Perceptually uniform and colour-blind safe", _table(_MAGMA), _BLUE, _GREEN),
    Colormap("plasma", "Plasma", "Indigo through magenta and orange to yellow — no black end. Perceptually uniform and colour-blind safe", _table(_PLASMA), (0, 0, 0), _GREEN),
    Colormap("inferno", "Inferno", "Black through purple, red and orange to pale yellow. Perceptually uniform and colour-blind safe", _table(_INFERNO), _BLUE, _GREEN),
    Colormap("cividis", "Cividis", "Navy through grey to yellow, made to look the same to red–green colour blindness as to anyone else. Perceptually uniform", _table(_CIVIDIS), _BLUE, _RED),
    Colormap("mako", "Mako", "Black through deep blue and teal to mint. Perceptually uniform and colour-blind safe", _table(_MAKO), _BLUE, _RED),
    Colormap("rocket", "Rocket", "Black through purple and red to cream. Perceptually uniform and colour-blind safe", _table(_ROCKET), _BLUE, _GREEN),
    Colormap("turbo", "Turbo", "A rainbow like jet, dark blue through green to dark red, but smooth — without the bands jet shows. Not for red–green colour blindness", _table(_TURBO), _BLUE, (255, 90, 170)),
)

COLORMAP_IDS = tuple(m.id for m in COLORMAPS)
DEFAULT = "jet"


def colormap_by_id(id_):
    """The map with this id, or jet for one this version does not know."""
    for m in COLORMAPS:
        if m.id == id_:
            return m
    return COLORMAPS[0]


def _js_round(x):
    # Math.round: halves go up, not to even.
    return np.floor(np.asarray(x, dtype=float) + 0.5)


def ramp(name, t):
    """Colours at positions `t` (clamped to 0…1) along a map's ramp, as uint8
    RGB, linear between stops. A scalar `t` gives one (3,) row."""
    m = colormap_by_id(name) if isinstance(name, str) else name
    s = m.stops.astype(float)
    last = len(s) - 1
    tt = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    u = tt * last
    i = np.minimum(last - 1, np.floor(u)).astype(int)
    f = (u - i)[..., None]
    return _js_round(s[i] + (s[i + 1] - s[i]) * f).astype(np.uint8)


def quantize(t, bands):
    """Snap ramp positions to the middle of one of `bands` equal steps, so a
    continuous map becomes a contour map. Fewer than 2 bands: unchanged."""
    if bands is None or not bands >= 2:
        return t
    u = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    return (np.minimum(bands - 1, np.floor(u * bands)) + 0.5) / bands


def scale_caps(name, reversed_=False):
    """The colours for a measured value below the scale's low end and above
    its high end: (low, high). A reversed scale runs off the other ends."""
    m = colormap_by_id(name) if isinstance(name, str) else name
    return (m.over, m.under) if reversed_ else (m.under, m.over)


def map_values(values, lo, hi, name=DEFAULT, bands=None, valid_min=-math.inf, valid_max=math.inf, reversed_=False):
    """Per-value uint8 RGB, shape (n, 3), for a scalar field.

    Three outcomes stay apart: within lo…hi gets the ramp (banded if `bands`);
    past it but still measured gets the map's cap for that end; outside the
    valid window, or NaN, gets the unmeasured grey. `reversed_` runs the ramp
    from its high end down, the way wall thickness reads (thin is hot)."""
    m = colormap_by_id(name)
    v = np.asarray(values, dtype=float).reshape(-1)
    out = np.empty((len(v), 3), dtype=np.uint8)
    with np.errstate(invalid="ignore"):
        valid = (v >= valid_min) & (v <= valid_max)
        over = valid & (v > hi)
        under = valid & (v < lo)
    inside = valid & ~over & ~under
    span = hi - lo
    inv = 1.0 / span if span > 0 else 0.0
    t = (v[inside] - lo) * inv
    if reversed_:
        t = 1.0 - t
    if bands:
        t = quantize(t, bands)
    out[inside] = ramp(m, t)
    cap_lo, cap_hi = scale_caps(m, reversed_)
    out[over] = cap_hi
    out[under] = cap_lo
    out[~valid] = UNMEASURED_RGB
    return out


def legend_stops(name, bands=None, reversed_=False, steps=64):
    """The legend's ramp from its low end (0) to its high end (1): a list of
    (position, rgb) for a continuous ramp, or of (from, to, rgb) bands."""
    m = colormap_by_id(name)

    def at(t):
        return 1.0 - t if reversed_ else t

    if bands and bands >= 2:
        return [(i / bands, (i + 1) / bands, tuple(int(c) for c in ramp(m, quantize(at((i + 0.5) / bands), bands))))
                for i in range(bands)]
    return [(i / steps, tuple(int(c) for c in ramp(m, at(i / steps)))) for i in range(steps + 1)]


def hex_rgb(h):
    """'#1877c0' as (24, 119, 192)."""
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def palette_color(i):
    """The i-th element's accent colour, wrapping after eight."""
    return PALETTE[i % len(PALETTE)]
